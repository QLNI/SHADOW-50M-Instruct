"""SHADOW 50M Reason - pilot-2 architecture = model50p (ternary DIFF + NoPE attention, frozen table io, cold
tier) + the INDEX HEAD (MSA-style ranker) + the three losses.
  L1  weighted token CE: weight 0 on FORCED positions (calc results after [eq], VM trace after [run]),
      3 on evidence/routing tokens ([need] line, [quote] line, [sol] value, span openers), 1 elsewhere.
      (L1 + L3 folded into one weighted CE; reported separately.)
  L2  retrieval InfoNCE: for each need-line with a gold record (the record whose pos= is later quoted),
      score = <idx(need)>, <idx(record)> over ALL records in the batch (in-batch hard negatives: same
      templates, near-keys, value collisions come free from the data). Index head reads DETACHED layer-L
      hidden states: it learns to predict, it never drags the main path.
Table v2 (65280 x 512 bits), unigram main. Attention: 1.5-bit ternary projections (binding rule), not the
250M's 1-bit. Constructed circuits are NOT wired in for this pilot (harness forces digits at decode, as in
pilot 1) - the G1 wiring is a separate checklist item.
"""
import math, os
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint

from model50 import TernLinear
from model50p import BlockP
from codec50 import FingerprintKV1

IDX_DIM = 128
BANK = 131072          # archive negative bank (kept, but only a fraction is sampled per query: see retrieval_loss)
HASH_CAND = 32        # the ranker's job: rerank the candidates a hash fetch returns (recall is the hash's job)


class BlockR(BlockP):
    """BlockP with configurable head geometry (tiny configs for smoke tests, full = 14/2/64)"""
    def __init__(self, d=896, dff=2464, nh=14, nkv=2, hd=64, layer=0):
        nn.Module.__init__(self)
        self.NH, self.NKV, self.HD = nh, nkv, hd
        self.n1, self.n2 = nn.RMSNorm(d), nn.RMSNorm(d)
        self.wq = TernLinear(d, nh * hd * 2); self.wk = TernLinear(d, nkv * hd * 2); self.wv = TernLinear(d, nkv * hd)
        self.wo = TernLinear(nh * hd, d); self.qn, self.kn = nn.RMSNorm(hd), nn.RMSNorm(hd)
        self.lam = nn.Parameter(torch.full((nh,), 0.8)); self.gate = nn.Parameter(torch.zeros(d))
        self.w1, self.w2 = TernLinear(d, dff), TernLinear(dff, d)
        # two-tier KV (250M law): hot window stays 16-bit; COLD archive K/V pass through the 1-bit codec (QAT from step 1)
        self.k1codec, self.k2codec, self.vcodec = FingerprintKV1(nkv, hd, seed=1000 + layer), FingerprintKV1(nkv, hd, seed=1500 + layer), FingerprintKV1(nkv, hd, seed=2000 + layer)

    def cold_kv_1bit(self, x, update, valid=None):
        k1, k2, v = self.kv_for_cold(x)
        q = lambda c, t: c.reconstruct_bits(c.bits(t, update=update, valid=valid), t.dtype)
        return (q(self.k1codec, k1), q(self.k2codec, k2), q(self.vcodec, v))


class ShadowR(nn.Module):
    def __init__(self, table_packed, unigram_bias, d=896, nlayers=6, code_bits=512, idx_layer=2, dff=2464, nh=14, nkv=2, hd=64):
        super().__init__()
        codes = np.unpackbits(table_packed, axis=1)[:, :code_bits].astype(np.float32) * 2 - 1
        self.register_buffer("C", torch.from_numpy(codes))
        self.register_buffer("ubias", torch.from_numpy(unigram_bias.astype(np.float32)))
        self.win = nn.Linear(code_bits, d, bias=False)
        self.wout = nn.Linear(d, code_bits, bias=False)
        self.blocks = nn.ModuleList(BlockR(d, dff, nh, nkv, hd, layer=i) for i in range(nlayers))
        self.cold_quant = True; self.codec_frozen = False
        self.register_buffer('bank', torch.zeros(BANK, IDX_DIM), persistent=False); self.register_buffer('bank_n', torch.zeros((), dtype=torch.long), persistent=False)   # training-only, never in the checkpoint
        self.nf = nn.RMSNorm(d)
        self.idx_layer = idx_layer
        self.idx_norm = nn.RMSNorm(d)
        self.idx = TernLinear(d, IDX_DIM)                 # the index head (ternary, tiny)
        self.idx_temp = nn.Parameter(torch.tensor(math.log(10.0)))
        self.gate_on = False; self.gate_beta = nn.Parameter(torch.full((nlayers,), 0.5))
        self.read_head = 0.0; self.read_head_stop = set()          # CONSTRUCTED reading head (frozen circuit, no parameters): strength > 0 turns it on at inference; 0 = off (training/export unaffected)   # head-gated attention (MSA coupling): score -> attention logits, layers > idx_layer
        self.grad_ckpt = False
        self.lane = None          # CalcLane (constructed, no parameters); attached for inference via attach_lane()

    def attach_lane(self, tables_dir):
        """attach the constructed tool circuits (arithmetic lane + calendar/units/count/compare/sort circuits) to the readout"""
        from tool_circuits import build_tool_circuits
        self.lane = build_tool_circuits(self, tables_dir, next(self.parameters()).device)
        # case-fold map for the constructed reading head: a token whose lowercase form is a single other token folds onto it
        # ("Fair" -> "fair", " Quiet" -> " quiet"), so need lines that change case still lock the right record.
        fold = {}
        vocab = getattr(self.lane, "vocab", [])
        for i, s in enumerate(vocab):
            if not s: continue
            canon = s.lower()
            if canon.startswith(" ") and len(canon) > 1: canon = canon[1:]          # " Gala" and "Gala" (line start) are the same key token
            if canon != s:
                try: j = self.lane.E.plain(canon, strict=False)
                except Exception: continue
                if len(j) == 1 and j[0] != i: fold[i] = j[0]
        self.read_head_fold = fold
        if not self.read_head_stop:                          # default stop set (the harness's): without it the audit's shipping@16 fell 1.00 -> 0.46
            self.read_head_stop = {t for w in ("count", "of", ".", " of", " count", "the", " the", "for", " for", "in", " in", chr(10)) for t in self.lane.E.plain(w, strict=False)}

    def logits_forced(self, h, ids):
        """logits for the LAST position + the constructed lane's forced readout computed over the WHOLE input
        sequence (the lane must see the open span). h: (B,1,d) last hidden; ids: (B,T) full input ids."""
        z = self.logits(h)
        if self.lane is not None: z = z + self.lane.force(self.C[ids], ids=ids)[:, -1:]
        return z

    def embed(self, ids):
        return self.win(self.C[ids])

    def logits(self, h, ids=None):
        z = self.wout(self.nf(h))
        z = (z @ self.C.t()) / math.sqrt(self.C.shape[1]) + self.ubias
        if ids is not None and not self.training:                                # the circuits are part of the readout at inference
            self._circuits_on(ids.device)
            if self.lane is not None: z = z + self.lane.force(self.C[ids], ids=ids)[:, -z.shape[1]:]
        return z

    def _circuits_on(self, dev):
        """the circuits hold no parameters, so moving the model rebuilds them on the new device rather than moving them"""
        if self.lane is not None and getattr(self.lane, "dev", None) is not None and str(self.lane.dev) == str(dev): return
        if self.lane is not None and str(getattr(self.lane, "dev", dev)) == str(dev): return
        self.lane = None
        self._build_circuits()

    def cold_from_past(self, past_ids):
        """cold K/V per layer for the past tokens + the layer-L hidden of the past (for record summaries)"""
        with torch.no_grad():
            x = self.embed(past_ids); colds = []; h_idx = None; valid = (past_ids != 2) & (past_ids != 0)   # codec stats + nothing else see the padding
            pos = torch.arange(x.shape[1], device=x.device)
            for li, b in enumerate(self.blocks):
                colds.append(b.cold_kv_1bit(x, update=self.training and not self.codec_frozen, valid=valid) if self.cold_quant else b.kv_for_cold(x))
                x = b.ffn_att(x, pos, None)
                if li == self.idx_layer: h_idx = x
        return colds, h_idx

    def forward(self, ids, past_ids=None):
        """training entry (goes through the DDP wrapper so gradients are synchronized): -> (h, h_idx, past_hidx)"""
        return self.hidden(ids, past_ids)

    def hidden(self, ids, past_ids=None):
        x = self.embed(ids); pos = torch.arange(ids.shape[1], device=ids.device)
        colds, past_hidx, cold_valid = (None, None, None)
        if past_ids is not None: colds, past_hidx = self.cold_from_past(past_ids); cold_valid = (past_ids != 2) & (past_ids != 0)   # eos/pad bucket padding is not archive
        h_idx = None; gb = None; rb = self.read_head_bias(ids, past_ids) if self.read_head > 0 else None
        for li, b in enumerate(self.blocks):
            cold = colds[li] if colds is not None else None
            bias = None if gb is None else gb * self.gate_beta[li]
            if rb is not None and li > self.idx_layer: bias = rb * self.read_head if bias is None else bias + rb * self.read_head
            if self.grad_ckpt and self.training: x = checkpoint(b.ffn_att, x, pos, cold, bias, cold_valid, use_reentrant=False)
            else: x = b.ffn_att(x, pos, cold, bias, cold_valid)
            if li == self.idx_layer:
                h_idx = x
                if self.gate_on: gb = self._head_bias(ids, x, past_ids, past_hidx)
        return x, h_idx, past_hidx

    def read_head_bias(self, ids, past_ids=None):
        """CONSTRUCTED reading head (2026-09-07 receipt: raw cold 0.36 -> 0.94 on ck_42000M, no training). Rule: after a need line, the
        record whose tokens contain the need line's key n-gram verbatim (longest match, >= 2 tokens) gets +1 on every key inside its
        [copen]..[cclose] span for every later query; 0 elsewhere. Pure token identity (same test as identical fingerprint codes)."""
        B, T = ids.shape; C_OPEN, C_CLOSE, NEED, OFF = 5, 6, 22, 32
        Tc = past_ids.shape[1] if past_ids is not None else 0; Tk = Tc + T
        out = torch.zeros(B, 1, T, Tk, dtype=torch.float32, device=ids.device)
        ids_c = ids.tolist(); past_c = past_ids.tolist() if past_ids is not None else None
        for b in range(B):
            recs = []
            for src, off in (((past_c[b], 0),) if past_c is not None else ()) + ((ids_c[b], Tc),):
                s_ = None
                for t, tok in enumerate(src):
                    if tok == C_OPEN: s_ = t
                    elif tok == C_CLOSE and s_ is not None and t > s_ + 1: recs.append((src[s_ + 1:t], off + s_ + 1, off + t)); s_ = None
            if not recs: continue
            for t, tok in enumerate(ids_c[b]):
                if tok != NEED: continue
                e = t + 1
                while e < T and ids_c[b][e] >= OFF and e < t + 24: e += 1
                fold = getattr(self, "read_head_fold", None) or {}
                key = [fold.get(u, u) for u in ids_c[b][t + 1:e] if u >= OFF and u not in self.read_head_stop]
                if not key: continue
                # the QUESTION carries the key verbatim even when the need line rewrote it (dropped digit, "count" for
                # "attendance"): its tokens (hot row up to the first [eot]) join the key for both the n-gram and the overlap
                EOT = 4; qe = ids_c[b].index(EOT) if EOT in ids_c[b] else 0
                qs = max([i + 1 for i in range(qe) if ids_c[b][i] == C_CLOSE] + [0])          # hot placement: skip the framed chunks, keep the question only
                qkey = [fold.get(u, u) for u in ids_c[b][qs:qe] if u >= OFF and u not in self.read_head_stop] if getattr(self, "read_head_question", False) else []   # OFF by default: probe 2026-09-08 hr@16 0.94 -> 0.81 with question tokens, others equal
                sources = [key] + ([qkey] if qkey else [])
                # score = (longest verbatim n-gram, bag overlap of key tokens): the n-gram wins when the key is copied verbatim;
                # the bag overlap survives rewritten keys ("C-467" for "C-4670", a dropped " 2", a changed attribute word,
                # case changes via the fold map) by counting how many key tokens the record contains at all.
                best, best_score = None, (0, 0)
                kset = set(key) | set(qkey)
                for ri, (toks, ks, ke) in enumerate(recs):
                    ft = [fold.get(u, u) for u in toks]
                    L = 0
                    for src in sources:
                        for n in range(len(src), max(1, L), -1):
                            if any(ft[i:i + n] == src[s0:s0 + n] for s0 in range(0, len(src) - n + 1) for i in range(0, len(ft) - n + 1)): L = max(L, n); break
                    ov = sum(1 for u in kset if u in ft)
                    sc = (L, ov)
                    if sc > best_score: best, best_score = ri, sc
                if best is not None and best_score[1] >= 1:
                    out[b, 0, e:, :] = 0.0                                     # a new need line releases the previous record (no stale bias on hop 2)
                    out[b, 0, e:, recs[best][1]:recs[best][2]] = 1.0
            # a record that has been QUOTED is released for every later query: the second [quote] / the next need line must
            # look elsewhere (audit 2026-09-08: the same record quoted twice was read as a conflict)
            QUOTE = 26
            for t, tok in enumerate(ids_c[b]):
                if tok != QUOTE: continue
                e = t + 1
                while e < T and ids_c[b][e] >= OFF and e < t + 96: e += 1
                qt = ids_c[b][t + 1:e]
                if len(qt) < 6: continue
                for toks, ks, ke in recs:
                    n = min(6, len(toks))
                    if n >= 4 and any(qt[i:i + n] == toks[s0:s0 + n] for s0 in range(0, len(toks) - n + 1) for i in range(0, len(qt) - n + 1)):
                        out[b, 0, e:, ks:ke] = 0.0
        return out

    def read_head_selected(self, ids, past_ids=None):
        """token ids of the record span the constructed head currently biases for the LAST position (None if no selection);
        used by the harness quote copier: after [quote] the record is copied verbatim instead of generated."""
        rb = self.read_head_bias(ids, past_ids)[0, 0, -1]
        nz = torch.nonzero(rb > 0).flatten()
        if len(nz) == 0: return None
        ks, ke = int(nz[0]), int(nz[-1]) + 1
        Tc = past_ids.shape[1] if past_ids is not None else 0
        allids = (past_ids[0].tolist() if past_ids is not None else []) + ids[0].tolist()
        return allids[ks:ke]

    def _head_bias(self, ids, h, past_ids=None, past_h=None):
        """(B,1,T,Tk) record bias: for query q after a need line, bias[q,k] = need_vec . rec_vec(k) for keys k inside a record
        span ([copen]..[cclose]) in the cold prefix or the hot row; 0 elsewhere. Head vectors NOT detached: the answer loss trains the head."""
        B, T = ids.shape; OFF = 32; C_OPEN, C_CLOSE, NEED = 5, 6, 22
        v = F.normalize(self.idx(self.idx_norm(h)), dim=-1)
        vp = F.normalize(self.idx(self.idx_norm(past_h)), dim=-1) if past_h is not None else None
        Tc = past_ids.shape[1] if past_ids is not None else 0; Tk = Tc + T
        out = torch.zeros(B, 1, T, Tk, dtype=v.dtype, device=v.device)
        ids_c = ids.tolist(); past_c = past_ids.tolist() if past_ids is not None else None
        for b in range(B):
            recs = []                                                            # (vec, key_start, key_end) over the concatenated key axis
            for src_ids, src_v, off in (((past_c[b], vp[b], 0),) if past_c is not None else ()) + ((ids_c[b], v[b], Tc),):
                s_ = None
                for t, tok in enumerate(src_ids):
                    if tok == C_OPEN: s_ = t
                    elif tok == C_CLOSE and s_ is not None and t > s_ + 1:
                        recs.append((src_v[s_ + 1:t].max(0).values, off + s_ + 1, off + t)); s_ = None
            needs = []                                                           # (vec, line_end) in the hot row
            for t, tok in enumerate(ids_c[b]):
                if tok == NEED:
                    e = t + 1
                    while e < T and ids_c[b][e] >= OFF and e < t + 24: e += 1
                    if e > t + 1: needs.append((v[b][t + 1:e].mean(0), e))
            if not recs or not needs: continue
            R = torch.stack([r[0] for r in recs]); Nv = torch.stack([n[0] for n in needs]); S = Nv @ R.t()   # (n_need, n_rec)
            recmap = torch.full((Tk,), -1, dtype=torch.long, device=v.device)
            for ri, (_, ks, ke) in enumerate(recs): recmap[ks:ke] = ri
            needmap = torch.full((T,), -1, dtype=torch.long, device=v.device)
            for ni, (_, e) in enumerate(needs): needmap[e:] = ni                  # latest need line governs later queries
            qm = needmap >= 0; km = recmap >= 0
            if qm.any() and km.any():
                Sfull = torch.cat([S, torch.zeros(S.shape[0], 1, device=v.device, dtype=v.dtype)], 1)     # column -1 -> 0
                Sfull = torch.cat([Sfull, torch.zeros(1, Sfull.shape[1], device=v.device, dtype=v.dtype)], 0)  # row -1 -> 0
                out[b, 0] = Sfull[needmap][:, recmap]
        return out

    def load_state_dict(self, sd, strict=True):
        sd = {k: v for k, v in sd.items() if k not in ("bank", "bank_n")}      # older checkpoints carried the bank
        if "gate_beta" not in sd: sd = dict(sd, gate_beta=self.gate_beta.detach().clone())   # pre-gate checkpoints
        r = super().load_state_dict(sd, strict=strict)
        self._build_circuits()
        return r

    def _build_circuits(self):
        """the constructed circuits hold no parameters, so they are rebuilt from the frozen table whenever weights load."""
        if self.lane is not None: return
        here = os.path.dirname(os.path.abspath(__file__))
        for d in (os.path.join(here, "..", "tables"), os.path.join(here, "..", "corpus"), os.path.join(here, "..", "tokenizer"),
                  os.path.join(here, "tables"), "tables", "corpus", "tokenizer"):
            if os.path.exists(os.path.join(d, "symbols_v2.json")):
                try:
                    self.attach_lane(d); return
                except Exception:
                    pass

    def generate(self, ids, max_new=128, stop=(4,)):
        """greedy continuation. ids: list[int] or (1,T) tensor; returns the new token ids."""
        self.eval()
        cur = list(ids[0].tolist() if torch.is_tensor(ids) else ids); n0 = len(cur)
        dev = next(self.parameters()).device
        with torch.no_grad():
            for _ in range(max_new):
                t = torch.tensor([cur], device=dev)
                h, _, _ = self.hidden(t)
                nxt = int(self.logits(h[:, -1:], t)[0, -1].argmax())
                cur.append(nxt)
                if nxt in stop: break
        return cur[n0:]

    def index_vec(self, h):
        """index-head vectors from (detached) hidden states: (B, T, IDX_DIM), L2-normalised"""
        return F.normalize(self.idx(self.idx_norm(h.detach())), dim=-1)

    def weighted_ce(self, h, y, w, chunk=None):
        """weighted token CE (weights 0/1/3); returns (loss, plain L1 over w>0 positions).
        The readout materializes a 65k-wide tensor per position: keep it in bf16 (half the traffic of .float())
        and chunk over time. CE itself upcasts internally, so the loss value is unchanged."""
        chunk = chunk or int(os.environ.get("CE_CHUNK", "512"))
        tot = torch.zeros((), device=h.device); tot1 = torch.zeros((), device=h.device); cnt = 0; cnt1 = 0
        for s in range(0, h.shape[1], chunk):
            lg = self.logits(h[:, s:s + chunk]); ys = y[:, s:s + chunk]; ws = w[:, s:s + chunk].float()
            ce = F.cross_entropy(lg.reshape(-1, lg.shape[-1]), ys.reshape(-1), reduction="none").view_as(ys)
            tot = tot + (ce * ws).sum(); cnt += int(ws.sum()); tot1 = tot1 + (ce * (ws > 0)).sum(); cnt1 += int((ws > 0).sum())
        return tot / max(cnt, 1), tot1 / max(cnt1, 1)

    def retrieval_loss(self, h_idx, past_hidx, spans):
        """spans: list over batch rows of dict(needs=[(s,e,gold_rec_id)], recs=[(src,s,e)]) with src in {hot,past}.
        Returns (L2, recall@1, n_queries). Record summary = max-pool over its tokens; need summary = mean-pool."""
        v_hot = self.index_vec(h_idx); v_past = self.index_vec(past_hidx) if past_hidx is not None else None
        recs, keys = [], []
        for bi, sp in enumerate(spans):
            for ri, (src, s, e) in enumerate(sp["recs"]):
                v = (v_hot[bi] if src == "hot" else v_past[bi])[s:e]
                if len(v) == 0: continue
                recs.append(v.max(dim=0).values); keys.append((bi, ri))
        if not recs: return torch.zeros((), device=h_idx.device), 0.0, 0
        R = torch.stack(recs); key_index = {k: i for i, k in enumerate(keys)}
        q, tgt = [], []
        for bi, sp in enumerate(spans):
            for (s, e, gold) in sp["needs"]:
                if (bi, gold) not in key_index or e <= s: continue
                q.append(v_hot[bi][s:e].mean(dim=0)); tgt.append(key_index[(bi, gold)])
        if not q: return torch.zeros((), device=h_idx.device), 0.0, 0
        Q = F.normalize(torch.stack(q), dim=-1); T = torch.tensor(tgt, device=h_idx.device)
        # RERANK FORMULATION (pilot-2 finding): the head must beat the hash INSIDE its candidate set, so each
        # query competes against (a) the records in its own row (the frames the fetch delivered) and (b) a small
        # sample of bank vectors standing in for other hash candidates. Ranking against 32k negatives taught a
        # global retriever, which a 128-d pooled vector cannot be.
        nb = int(self.bank_n)
        per_row = {}
        for i, (bi, _ri) in enumerate(keys): per_row.setdefault(bi, []).append(i)
        losses = []; hits = 0
        for qi, (bi, gold_idx) in enumerate([(k[0], t) for k, t in zip([keys[t] for t in tgt], tgt)]):
            idx = list(per_row.get(bi, []))
            if gold_idx not in idx: idx.append(gold_idx)
            if nb > 0 and len(idx) < HASH_CAND:
                extra = torch.randint(0, nb, (HASH_CAND - len(idx),), device=R.device)
                cand = torch.cat([R[idx], self.bank[extra].to(R.dtype)], 0)
            else: cand = R[idx]
            pos = idx.index(gold_idx)
            lg = (Q[qi:qi + 1] @ cand.t()) * self.idx_temp.exp()
            losses.append(F.cross_entropy(lg, torch.tensor([pos], device=R.device)))
            hits += int(int(lg.argmax()) == pos)
        loss = torch.stack(losses).mean(); rec1 = hits / max(1, len(losses))
        with torch.no_grad():                                                    # push this batch's records into the FIFO bank
            r = R.detach().float(); n = r.shape[0]; start = int(self.bank_n) % BANK
            if start + n <= BANK: self.bank[start:start + n] = r
            else: k = BANK - start; self.bank[start:] = r[:k]; self.bank[:n - k] = r[k:]
            self.bank_n += 0; self.bank_n.fill_(min(BANK, nb + n) if nb + n <= BANK else BANK)
        return loss, rec1, len(tgt)

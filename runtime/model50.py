"""SHADOW 50M Reasoning — pilot model (PHASE1 stack, faithful mini implementation).

Stack: frozen fingerprint table (0 params) -> fp16 dense io projections 512<->896 ->
6 blocks [ternary QKVO + two-tier KV (hot RoPE window + cold position-free top-k) +
QK-norm + output gate + ternary FFN 896->2464] -> tied popcount-style readout + unigram
bias. int8 pow2 (pot) fake-quant on linear inputs, STE everywhere, requant every step.
q4r taps (AR signed commit / AI unresolved) with coherence C — OFF by default, enabled
for the anneal tail (gate-only: C biases attention temperature).
"""
import math, os
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


# ---------- quant helpers (STE) ----------

class _PotInt8(torch.autograd.Function):
    """power-of-two dynamic absmax int8 fake-quant with a straight-through backward, no host sync, one pass."""
    @staticmethod
    def forward(ctx, x):
        s = x.detach().abs().amax()
        scale = torch.where(s > 0, 2.0 ** torch.ceil(torch.log2(s / 127.0 + 1e-12)), torch.ones_like(s))
        return torch.clamp(torch.round(x / scale), -127, 127) * scale
    @staticmethod
    def backward(ctx, g):
        return g


def pot_int8(x):
    """power-of-two dynamic absmax int8 fake-quant, STE (identical values to the original formulation)."""
    return _PotInt8.apply(x)


class _TernSTE(torch.autograd.Function):
    """forward returns EXACTLY q*alpha (bit-identical to the deploy pack's dequant), backward is straight-through."""
    @staticmethod
    def forward(ctx, w):
        alpha = w.abs().mean(dim=1, keepdim=True) + 1e-8
        return torch.clamp(torch.round(w / alpha), -1, 1) * alpha
    @staticmethod
    def backward(ctx, g): return g


def ternary(w):
    """absmean per-row ternary {-1,0,+1}*alpha, STE (requant every forward); bit-exact vs the export."""
    return _TernSTE.apply(w)


class _TernInt8(torch.autograd.Function):
    """int8 tensor-core forward for a ternary layer: y = (int8(x/scale) @ int8(w/alpha)^T) * scale * alpha is EXACT integer
    arithmetic (the bf16 path rounds the same product); backward = the same straight-through gradients as pot_int8 + ternary,
    computed from the saved int8 tensors (half the saved-activation memory of the bf16 path)."""
    @staticmethod
    def forward(ctx, x, w):
        s = x.detach().abs().amax(); scale = torch.where(s > 0, 2.0 ** torch.ceil(torch.log2(s / 127.0 + 1e-12)), torch.ones_like(s))
        xq = torch.clamp(torch.round(x / scale), -127, 127).to(torch.int8)
        alpha = w.detach().abs().mean(dim=1, keepdim=True) + 1e-8
        wq = torch.clamp(torch.round(w.detach() / alpha), -1, 1).to(torch.int8)
        din, dout = w.shape[1], w.shape[0]
        y = torch._int_mm(xq.reshape(-1, din), wq.t().contiguous())                      # int32 (N, dout)
        y = y.to(x.dtype) * (scale.to(x.dtype) * alpha.t().to(x.dtype))
        ctx.save_for_backward(xq, wq, scale, alpha); ctx.xshape = x.shape
        return y.reshape(*x.shape[:-1], dout)
    @staticmethod
    def backward(ctx, g):
        xq, wq, scale, alpha = ctx.saved_tensors; din, dout = wq.shape[1], wq.shape[0]
        g2 = g.reshape(-1, dout)
        wf = wq.to(g.dtype) * alpha.to(g.dtype)                                          # (dout, din) = ternary(w) values
        grad_x = (g2 @ wf).reshape(ctx.xshape)                                           # STE through pot_int8
        grad_w = g2.t() @ (xq.reshape(-1, din).to(g.dtype) * scale.to(g.dtype))          # STE through ternary
        return grad_x, grad_w


INT8 = os.environ.get("SHADOW_INT8", "0") == "1"   # opt-in: slower on the 3080 (10.2 vs 8.8 ms), measured on Ada separately


class TernLinear(nn.Module):
    def __init__(self, din, dout):
        super().__init__()
        self.w = nn.Parameter(torch.empty(dout, din))
        nn.init.normal_(self.w, std=0.02)
        self.frozen = False        # deployment mode: w already holds alpha*q, skip requant
    def forward(self, x, prequant=False):
        if INT8 and not self.frozen and x.is_cuda and x.shape[:-1].numel() > 16 and self.w.shape[0] % 8 == 0 and self.w.shape[1] % 8 == 0:
            return _TernInt8.apply(x, self.w)                                             # prequant input is idempotent under the same scale
        w = self.w if self.frozen else ternary(self.w)
        return F.linear(x if prequant else pot_int8(x), w)


# ---------- rope ----------

def rope(q, k, pos, theta=100_000.0):
    d = q.shape[-1]
    inv = 1.0 / (theta ** (torch.arange(0, d, 2, device=q.device).float() / d))
    ang = pos.float()[:, None] * inv[None, :]                    # (T, d/2)
    cos, sin = ang.cos()[None, None], ang.sin()[None, None]
    def rot(x):
        x1, x2 = x[..., 0::2], x[..., 1::2]
        return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)
    return rot(q), rot(k)


# ---------- block ----------

class Block(nn.Module):
    NH, NKV, HD = 14, 2, 64

    def __init__(self, d=896, dff=2464, layer_idx=0):
        super().__init__()
        from codec50 import FingerprintKV1
        self.kcodec = FingerprintKV1(self.NKV, self.HD, seed=1000 + layer_idx)
        self.vcodec = FingerprintKV1(self.NKV, self.HD, seed=2000 + layer_idx)
        self.n1, self.n2 = nn.RMSNorm(d), nn.RMSNorm(d)
        self.wq = TernLinear(d, self.NH * self.HD)
        self.wk = TernLinear(d, self.NKV * self.HD)
        self.wv = TernLinear(d, self.NKV * self.HD)
        self.wo = TernLinear(self.NH * self.HD, d)
        self.qn, self.kn = nn.RMSNorm(self.HD), nn.RMSNorm(self.HD)
        self.gate = nn.Parameter(torch.zeros(d))                 # output gate (full prec)
        self.w1, self.w2 = TernLinear(d, dff), TernLinear(dff, d)
        self.cold_topk = 0                                       # >0: per-head top-k over cold (deploy-consistent)

    def att(self, x, pos, cold_k=None, cold_v=None, q4_temp=None):
        B, T, _ = x.shape
        h = self.n1(x)
        q = self.wq(h).view(B, T, self.NH, self.HD).transpose(1, 2)
        k = self.wk(h).view(B, T, self.NKV, self.HD).transpose(1, 2)
        v = self.wv(h).view(B, T, self.NKV, self.HD).transpose(1, 2)
        q, k = self.qn(q), self.kn(k)
        q, k = rope(q, k, pos)
        k = k.repeat_interleave(self.NH // self.NKV, dim=1)
        v = v.repeat_interleave(self.NH // self.NKV, dim=1)
        if q4_temp is not None:
            q = q * q4_temp                                      # q4 gate biases attention temp
        if cold_k is not None:
            # cold tokens: position-free prefix memory (no RoPE), no causal mask on them
            ck = cold_k.repeat_interleave(self.NH // self.NKV, dim=1)
            cv = cold_v.repeat_interleave(self.NH // self.NKV, dim=1)
            k, v = torch.cat([ck, k], dim=2), torch.cat([cv, v], dim=2)
            Tc = ck.shape[2]
            mask = torch.ones(1, 1, T, Tc + T, dtype=torch.bool, device=x.device).expand(
                q.shape[0], self.NH, T, Tc + T).clone()
            mask[..., Tc:] = torch.tril(torch.ones(T, T, dtype=torch.bool, device=x.device))
            if self.cold_topk and Tc > self.cold_topk:
                # deploy-consistent: each head may only see its top-k cold tokens
                # (scored in codec space, exactly what the deployed Hamming+rerank returns)
                sc = q @ ck.transpose(-1, -2)                    # (B,NH,T,Tc)
                thr = sc.topk(self.cold_topk, dim=-1).values[..., -1:]
                mask[..., :Tc] = sc >= thr
            o = F.scaled_dot_product_attention(q, k, v, attn_mask=mask)
        else:
            o = F.scaled_dot_product_attention(q, k, v, is_causal=True)   # flash path
        o = o.transpose(1, 2).reshape(B, T, -1)
        return x + torch.sigmoid(self.gate) * self.wo(o)

    def kv_for_cold(self, x):
        """K,V of a (no-grad) past segment for the cold store — position-free."""
        B, T, _ = x.shape
        h = self.n1(x)
        k = self.kn(self.wk(h).view(B, T, self.NKV, self.HD).transpose(1, 2))
        v = self.wv(h).view(B, T, self.NKV, self.HD).transpose(1, 2)
        return k, v

    def ffn(self, x):
        return x + self.w2(F.silu(self.w1(self.n2(x))))


class Shadow50(nn.Module):
    def __init__(self, table_packed, unigram_bias, d=896, nlayers=6, code_bits=512):
        super().__init__()
        codes = np.unpackbits(table_packed, axis=1)[:, :code_bits].astype(np.float32) * 2 - 1
        self.register_buffer("C", torch.from_numpy(codes))               # (V,512) frozen +-1
        self.register_buffer("ubias", torch.from_numpy(unigram_bias.astype(np.float32)))
        self.win = nn.Linear(code_bits, d, bias=False)                    # fp16-class dense io
        self.wout = nn.Linear(d, code_bits, bias=False)
        self.blocks = nn.ModuleList([Block(d, layer_idx=i) for i in range(nlayers)])
        self.nf = nn.RMSNorm(d)
        # q4r taps (gate-only). OFF unless q4_on.
        self.q4_r = nn.Linear(d, 1, bias=False)
        self.q4_i = nn.Linear(d, 1, bias=False)
        nn.init.zeros_(self.q4_r.weight); nn.init.zeros_(self.q4_i.weight)
        self.q4_on = False
        self.cold_quant = False   # trained-in cold-key compression (sign * per-row scale)

    def embed(self, ids):
        return self.win(self.C[ids])

    def logits(self, h):
        z = self.wout(self.nf(h))                                        # (B,T,512)
        return (z @ self.C.t()) / math.sqrt(self.C.shape[1]) + self.ubias

    def cold_from_past(self, past_ids, topk=32, chunk=512):
        """Gradient-free pass over past tokens -> per-layer cold K/V, then per-layer
        top-k selection happens against the hot query mean (cheap pilot form: keep all,
        select by K-signature Hamming to mean hot K later). Pilot keeps all cold K/V and
        lets attention softmax select (T_cold <= 2048), matching 'trained-in' gradients
        on the hot side while cold side stays frozen."""
        with torch.no_grad():
            x = self.embed(past_ids)
            colds = []
            for b in self.blocks:
                k, v = b.kv_for_cold(x)
                if self.cold_quant:      # 250M-proven FingerprintKV1: calibrated 1-bit K AND V
                    upd = self.training and not getattr(self, "codec_frozen", False)
                    k = b.kcodec.reconstruct_bits(b.kcodec.bits(k, update=upd), k.dtype)
                    v = b.vcodec.reconstruct_bits(b.vcodec.bits(v, update=upd), v.dtype)
                colds.append((k, v))
                pos = torch.arange(x.shape[1], device=x.device)
                x = b.ffn(b.att(x, pos))
        return colds

    def hidden(self, ids, past_ids=None):
        """Final hidden states (pre-readout) — pair with chunked_ce to avoid the
        (B,T,V) float32 logits tensor (6+ GB at production shapes)."""
        x = self.embed(ids)
        pos = torch.arange(ids.shape[1], device=ids.device)
        colds = self.cold_from_past(past_ids) if past_ids is not None else None
        for li, b in enumerate(self.blocks):
            ck, cv = (colds[li] if colds is not None else (None, None))
            x = b.ffn(b.att(x, pos, ck, cv))
        return x

    def chunked_ce(self, h, y, chunk=256, ignore_index=0):
        tot, cnt = 0.0, 0
        for s in range(0, h.shape[1], chunk):
            lg = self.logits(h[:, s:s + chunk]).float()
            ys = y[:, s:s + chunk]
            n = (ys != ignore_index).sum()
            if n == 0: continue
            tot = tot + torch.nn.functional.cross_entropy(
                lg.reshape(-1, lg.shape[-1]), ys.reshape(-1),
                ignore_index=ignore_index, reduction="sum")
            cnt = cnt + n
        return tot / cnt.clamp(min=1)

    def forward(self, ids, past_ids=None, q4_report=False, targets=None):
        """targets given -> returns chunked-CE loss (computed inside forward so DDP
        syncs io/readout grads). q4_report -> also returns live AR/AI/C dict."""
        x = self.embed(ids)
        pos = torch.arange(ids.shape[1], device=ids.device)
        colds = self.cold_from_past(past_ids) if past_ids is not None else None
        AR = torch.zeros(ids.shape[0], device=ids.device)
        AI = torch.zeros(ids.shape[0], device=ids.device)
        q4_temp = None
        for li, b in enumerate(self.blocks):
            ck, cv = (colds[li] if colds is not None else (None, None))
            x = b.att(x, pos, ck, cv, q4_temp)
            x = b.ffn(x)
            if self.q4_on:
                hm = x.mean(dim=1)
                hm = hm * torch.rsqrt(hm.pow(2).mean(-1, keepdim=True) + 1e-6)  # pilot fix: no tap saturation
                AR = AR + torch.tanh(self.q4_r(hm)).squeeze(-1)          # signed commit
                AI = AI + torch.tanh(self.q4_i(hm)).squeeze(-1).abs()    # unresolved mass
                C = AR.abs() / (AR.abs() + AI + 1e-6)
                q4_temp = (0.9 + 0.2 * C).view(-1, 1, 1, 1)              # gate-only bias
        if targets is not None:
            loss = self.chunked_ce(x, targets)
            if q4_report:
                C = AR.abs() / (AR.abs() + AI + 1e-6)
                return loss, {"AR": AR, "AI": AI, "C": C}
            return loss
        out = self.logits(x)
        if q4_report:
            C = AR.abs() / (AR.abs() + AI + 1e-6)
            return out, {"AR": AR, "AI": AI, "C": C}   # live tensors; caller detaches for logging
        return out

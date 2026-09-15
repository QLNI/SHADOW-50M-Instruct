"""SHADOW pilot architecture: model50 fork with
- DIFF attention (each head has a subtractive twin; per-head learnable lambda)
- NoPE content group (KV group 0 keeps RoPE = syntax group; group 1 skips = content group)
- ternary everywhere (binding law), frozen fingerprint table io, cold tier kept
- q4 taps removed (retired); manual attention with per-block grad checkpointing
"""
import math, os
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint

from model50 import TernLinear, pot_int8, rope


class BlockP(nn.Module):
    NH, NKV, HD = 14, 2, 64

    def __init__(self, d=896, dff=2464):
        super().__init__()
        self.n1, self.n2 = nn.RMSNorm(d), nn.RMSNorm(d)
        self.wq = TernLinear(d, self.NH * self.HD * 2)     # main + twin
        self.wk = TernLinear(d, self.NKV * self.HD * 2)
        self.wv = TernLinear(d, self.NKV * self.HD)
        self.wo = TernLinear(self.NH * self.HD, d)
        self.qn, self.kn = nn.RMSNorm(self.HD), nn.RMSNorm(self.HD)
        self.lam = nn.Parameter(torch.full((self.NH,), 0.8))
        self.gate = nn.Parameter(torch.zeros(d))
        self.w1, self.w2 = TernLinear(d, dff), TernLinear(dff, d)

    def _qkv(self, h, B, T):
        hq = pot_int8(h)                                   # quantize ONCE, shared by the three projections
        q = self.qn(self.wq(hq, True).view(B, T, self.NH * 2, self.HD).transpose(1, 2))
        k = self.kn(self.wk(hq, True).view(B, T, self.NKV * 2, self.HD).transpose(1, 2))
        v = self.wv(hq, True).view(B, T, self.NKV, self.HD).transpose(1, 2)
        return q, k, v

    def _rope_groups(self, t, pos, n_groups):
        """RoPE on group 0 (syntax); group 1 stays NoPE (content). Layout: for q,
        heads [0:NH] main / [NH:2NH] twin, each half split NKV-wise by repeat
        pattern; we rotate the first half of heads within each map."""
        half = t.shape[1] // n_groups                     # heads per group-slot
        parts = []
        for g in range(n_groups):
            seg = t[:, g * half:(g + 1) * half]
            parts.append(rope_seg(seg, pos) if g % 2 == 0 else seg)
        return torch.cat(parts, dim=1)

    def att(self, x, pos, cold_k=None, cold_v=None, bias=None, cold_valid=None):
        B, T, _ = x.shape
        h = self.n1(x)
        q, k, v = self._qkv(h, B, T)
        R = self.NH // self.NKV
        # split main/twin maps
        q1, q2 = q[:, :self.NH], q[:, self.NH:]
        k1, k2 = k[:, :self.NKV], k[:, self.NKV:]
        # RoPE: within each map, KV group 0 (and its query heads) rotate; group 1 NoPE
        def rot_q(qm):
            a = rope_seg(qm[:, :R], pos)                  # heads of group 0
            return torch.cat([a, qm[:, R:]], dim=1)
        def rot_k(km):
            a = rope_seg(km[:, :1], pos)
            return torch.cat([a, km[:, 1:]], dim=1)
        q1, q2, k1, k2 = rot_q(q1), rot_q(q2), rot_k(k1), rot_k(k2)
        # GQA expansion: 2 KV heads -> 14 query heads, twice (DIFF). repeat_interleave COPIES ~117MB per tensor
        # per layer; torch >= 2.5 does the broadcast inside flash attention (enable_gqa), no copy at all.
        # GQA: the flash kernel broadcasts 2 KV heads to 14 natively on the CAUSAL (hot-only) path with torch >= 2.5 -> no copies.
        # The cold path carries a boolean mask, which only the efficient/math kernels accept, and those do NOT broadcast GQA
        # (native GQA there falls to the MATH kernel, 10x slower, measured 2026-09-04) -> repeat_interleave on that path only.
        GQA = getattr(F, "_shadow_gqa", None)
        if GQA is None:
            try:
                _q = torch.zeros(1, 4, 16, 8, device=x.device, dtype=x.dtype); _t = torch.zeros(1, 2, 16, 8, device=x.device, dtype=x.dtype)
                from torch.nn.attention import sdpa_kernel, SDPBackend
                with sdpa_kernel(SDPBackend.FLASH_ATTENTION): F.scaled_dot_product_attention(_q, _t, _t, is_causal=True, enable_gqa=True)
                GQA = os.environ.get("SHADOW_GQA", "1") == "1"
            except Exception: GQA = False
            F._shadow_gqa = GQA
        if cold_k is not None or not GQA:
            k1 = k1.repeat_interleave(R, dim=1); k2 = k2.repeat_interleave(R, dim=1); vv = v.repeat_interleave(R, dim=1); GQA = False
        else:
            vv = v
        # DIFF via linearity: (A1 - lam*A2) @ V = A1@V - lam*(A2@V)
        # -> two fused flash-attention calls, no explicit TxT score maps.
        if cold_k is not None:
            ck1, ck2, cv = cold_k
            if not GQA:
                ck1 = ck1.repeat_interleave(R, dim=1); ck2 = ck2.repeat_interleave(R, dim=1); cvv = cv.repeat_interleave(R, dim=1)
            else: cvv = cv
            k1 = torch.cat([ck1, k1], dim=2); k2 = torch.cat([ck2, k2], dim=2)
            vv = torch.cat([cvv, vv], dim=2)
            Tc = ck1.shape[2]
            mask = torch.ones(T, Tc + T, dtype=torch.bool, device=x.device)
            mask[:, Tc:] = torch.tril(torch.ones(T, T, dtype=torch.bool, device=x.device))
            if cold_valid is not None:                                 # (B,Tc) bool: hot tokens see only REAL archive tokens, never the bucket padding
                mask = mask[None, None].expand(B, 1, T, Tc + T).clone(); mask[:, :, :, :Tc] &= cold_valid[:, None, None, :]
            kw = {"enable_gqa": True} if GQA else {}
            if bias is not None:                                   # head-gated: float mask = record bias + causal(-inf)
                fm = torch.zeros(mask.shape, dtype=q1.dtype, device=x.device).masked_fill(~mask, float("-inf"))   # mask is (T,Tk) or (B,1,T,Tk) with cold_valid
                mask = (fm[None, None] if fm.dim() == 2 else fm) + bias.to(q1.dtype)
            o1 = F.scaled_dot_product_attention(q1, k1, vv, attn_mask=mask, **kw)
            o2 = F.scaled_dot_product_attention(q2, k2, vv, attn_mask=mask, **kw)
        elif bias is not None:
            kw = {"enable_gqa": True} if GQA else {}
            fm = torch.zeros(T, T, dtype=q1.dtype, device=x.device).masked_fill(~torch.tril(torch.ones(T, T, dtype=torch.bool, device=x.device)), float("-inf"))
            mask = fm[None, None] + bias.to(q1.dtype)
            o1 = F.scaled_dot_product_attention(q1, k1, vv, attn_mask=mask, **kw)
            o2 = F.scaled_dot_product_attention(q2, k2, vv, attn_mask=mask, **kw)
        else:
            kw = {"enable_gqa": True} if GQA else {}
            o1 = F.scaled_dot_product_attention(q1, k1, vv, is_causal=True, **kw)
            o2 = F.scaled_dot_product_attention(q2, k2, vv, is_causal=True, **kw)
        o = (o1 - self.lam.view(1, -1, 1, 1) * o2).transpose(1, 2).reshape(B, T, -1) if os.environ.get("SHADOW_DIFF", "1") == "1" else o1.transpose(1, 2).reshape(B, T, -1)   # SHADOW_DIFF=0: speed measurement only (twin still projected)
        return x + torch.sigmoid(self.gate) * self.wo(o)

    def kv_for_cold(self, x):
        B, T, _ = x.shape
        h = self.n1(x); hq = pot_int8(h)
        k = self.kn(self.wk(hq, True).view(B, T, self.NKV * 2, self.HD).transpose(1, 2))
        v = self.wv(hq, True).view(B, T, self.NKV, self.HD).transpose(1, 2)
        return (k[:, :self.NKV], k[:, self.NKV:], v)      # (k1, k2, v) — all NoPE by nature

    def ffn(self, x):
        return x + self.w2(F.silu(self.w1(self.n2(x))))

    def ffn_att(self, x, pos, cold, bias=None, cold_valid=None):
        x = self.att(x, pos, cold_k=cold, cold_v=None, bias=bias, cold_valid=cold_valid) if cold is not None else self.att(x, pos, bias=bias)
        return self.ffn(x)


def rope_seg(t, pos):
    d = t.shape[-1]
    inv = 1.0 / (100_000.0 ** (torch.arange(0, d, 2, device=t.device).float() / d))
    ang = pos.float()[:, None] * inv[None, :]
    cos, sin = ang.cos()[None, None], ang.sin()[None, None]
    x1, x2 = t[..., 0::2], t[..., 1::2]
    return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)


class ShadowP(nn.Module):
    def __init__(self, table_packed, unigram_bias, d=896, nlayers=6, code_bits=512):
        super().__init__()
        codes = np.unpackbits(table_packed, axis=1)[:, :code_bits].astype(np.float32) * 2 - 1
        self.register_buffer("C", torch.from_numpy(codes))
        self.register_buffer("ubias", torch.from_numpy(unigram_bias.astype(np.float32)))
        self.win = nn.Linear(code_bits, d, bias=False)
        self.wout = nn.Linear(d, code_bits, bias=False)
        self.blocks = nn.ModuleList(BlockP(d) for _ in range(nlayers))
        self.nf = nn.RMSNorm(d)
        self.grad_ckpt = True

    def embed(self, ids):
        return self.win(self.C[ids])

    def logits(self, h):
        z = self.wout(self.nf(h))
        return (z @ self.C.t()) / math.sqrt(self.C.shape[1]) + self.ubias

    def cold_from_past(self, past_ids):
        with torch.no_grad():
            x = self.embed(past_ids)
            colds = []
            pos = torch.arange(x.shape[1], device=x.device)
            for b in self.blocks:
                colds.append(b.kv_for_cold(x))
                x = b.ffn_att(x, pos, None)
        return colds

    def hidden(self, ids, past_ids=None):
        x = self.embed(ids)
        pos = torch.arange(ids.shape[1], device=ids.device)
        colds = self.cold_from_past(past_ids) if past_ids is not None else None
        for li, b in enumerate(self.blocks):
            cold = colds[li] if colds is not None else None
            if self.grad_ckpt and self.training:
                x = checkpoint(b.ffn_att, x, pos, cold, use_reentrant=False)
            else:
                x = b.ffn_att(x, pos, cold)
        return x

    def chunked_ce(self, h, y, chunk=256, ignore_index=0):
        tot, cnt = 0.0, 0
        for s in range(0, h.shape[1], chunk):
            lg = self.logits(h[:, s:s + chunk]).float()
            ys = y[:, s:s + chunk]
            n = (ys != ignore_index).sum()
            if n == 0: continue
            tot = tot + F.cross_entropy(lg.reshape(-1, lg.shape[-1]), ys.reshape(-1),
                                        ignore_index=ignore_index, reduction="sum")
            cnt = cnt + n
        return tot / max(cnt, 1)

    def forward(self, ids, past_ids=None, targets=None):
        h = self.hidden(ids, past_ids)
        if targets is not None:
            return self.chunked_ce(h, targets)
        return self.logits(h)

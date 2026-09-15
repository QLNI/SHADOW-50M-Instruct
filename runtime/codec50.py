"""FingerprintKV1 — the 250M's PROVEN trained-in 1-bit KV codec, ported verbatim
sign flip -> Walsh-Hadamard -> mean-center ->
calibrated median threshold -> 1 bit/dim -> two-centroid decode. STE in training.
Calibration: EMA during training, frozen (checkpointed buffers) at eval.
"""
import torch
import torch.nn as nn


class _ExactSTE(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x, q): return q
    @staticmethod
    def backward(ctx, g): return g, None


def ste(x, q): return _ExactSTE.apply(x, q)


def walsh_hadamard(x):
    n = x.shape[-1]
    if n < 1 or n & (n - 1):
        raise ValueError(f"Walsh-Hadamard width must be a power of two, got {n}")
    y = x
    h = 1
    while h < n:
        y = y.reshape(*x.shape[:-1], n // (2 * h), 2, h)
        a, b = y[..., 0, :], y[..., 1, :]
        y = torch.stack([a + b, a - b], dim=-2).reshape(*x.shape[:-1], n)
        h *= 2
    return y / (n ** 0.5)


class FingerprintKV1(nn.Module):
    """One bit per value, no per-token scale. (B, heads, T, width) tensors."""
    def __init__(s, heads, width, seed=0, momentum=0.01, decision_grid=256.0):
        super().__init__()
        if width < 1 or width & (width - 1):
            raise ValueError(f"width must be power of two, got {width}")
        g = torch.Generator().manual_seed(int(seed))
        sign = (torch.randint(0, 2, (heads, width), generator=g, dtype=torch.int8) * 2 - 1)
        s.heads, s.width, s.momentum = int(heads), int(width), float(momentum)
        s.decision_grid = float(decision_grid)
        s.register_buffer("sign", sign)
        s.register_buffer("mu", torch.zeros(heads, width))
        s.register_buffer("ctv", torch.zeros(heads, width))
        s.register_buffer("low", torch.full((heads, width), -1.0))
        s.register_buffer("high", torch.ones(heads, width))
        s.register_buffer("initialized", torch.tensor(False))

    @torch.no_grad()
    def calibrate(s, x, valid=None):
        if valid is not None:                                              # (B,T) bool: statistics over REAL archive tokens only (bucket padding excluded)
            x = x.permute(0, 2, 1, 3)[valid].permute(1, 0, 2)[None]         # (B,H,T,W) -> (1,H,N,W)
        xf = x.detach().float()
        mu = xf.mean((0, 2))
        sg = s.sign.float()[None, :, None, :]
        z = walsh_hadamard((xf - mu[None, :, None, :]) * sg)
        flat = z.permute(1, 0, 2, 3).reshape(s.heads, -1, s.width)
        decision = (flat * s.decision_grid).round() / s.decision_grid
        ctv = decision.median(1).values
        hi = decision > ctv[:, None, :]; lo = ~hi
        low = (flat * lo).sum(1) / lo.sum(1).clamp_min(1)
        high = (flat * hi).sum(1) / hi.sum(1).clamp_min(1)
        rate = 1.0 if not bool(s.initialized) else s.momentum
        for dst, src in ((s.mu, mu), (s.ctv, ctv), (s.low, low), (s.high, high)):
            dst.lerp_(src.to(dst.dtype), rate)
        s.initialized.fill_(True)
        return s

    def transform(s, x):
        sg = s.sign.to(x.dtype)[None, :, None, :]
        return walsh_hadamard((x - s.mu.to(x.dtype)[None, :, None, :]) * sg)

    def bits(s, x, update=False, valid=None):
        if update or not bool(s.initialized): s.calibrate(x, valid)
        decision = (s.transform(x) * s.decision_grid).round() / s.decision_grid
        threshold = (s.ctv.to(x.dtype) * s.decision_grid).round() / s.decision_grid
        return decision > threshold[None, :, None, :]

    def reconstruct_bits(s, bits, dtype=torch.float32):
        low = s.low.to(dtype)[None, :, None, :]
        high = s.high.to(dtype)[None, :, None, :]
        rotated = torch.where(bits, high, low)
        sg = s.sign.to(dtype)[None, :, None, :]
        return s.mu.to(dtype)[None, :, None, :] + walsh_hadamard(rotated) * sg

    def forward(s, x):
        b = s.bits(x, update=s.training)
        return ste(x, s.reconstruct_bits(b, x.dtype))

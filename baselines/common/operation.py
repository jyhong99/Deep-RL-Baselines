import torch
import operator
from typing import Callable


# https://github.com/Stable-Baselines-Team/stable-baselines3-contrib/blob/master/sb3_contrib/common/utils.py
def quantile_huber_loss(current_quantiles, target_quantiles, weights=None, sum_over_quantiles=True, device='cpu'):
    n_quantiles = current_quantiles.shape[-1]
    tau = (torch.arange(n_quantiles, device=device, dtype=torch.float) + 0.5) / n_quantiles
    if current_quantiles.ndim == 2:
        tau = tau.view(1, -1, 1)
    elif current_quantiles.ndim == 3:
        tau = tau.view(1, 1, -1, 1)

    pairwise_delta = target_quantiles.unsqueeze(-2) - current_quantiles.unsqueeze(-1)
    abs_pairwise_delta = torch.abs(pairwise_delta)
    huber_loss = torch.where(abs_pairwise_delta > 1, abs_pairwise_delta - 0.5, pairwise_delta ** 2 * 0.5)
    loss = torch.abs(tau - (pairwise_delta.detach() < 0).float()) * huber_loss
    if weights is not None:
        loss = (weights.view(-1, 1, 1) * loss).sum(dim=-2).mean() if sum_over_quantiles else (weights.view(-1, 1, 1, 1) * loss).mean()
    else:
        loss = loss.sum(dim=-2).mean() if sum_over_quantiles else loss.mean()
    return loss, pairwise_delta.sum(dim=1).mean(dim=1, keepdim=True)


# https://github.com/DLR-RM/stable-baselines3/blob/master/stable_baselines3/common/distributions.py#L620
class TanhBijector:
    def __init__(self, epsilon: float = 1e-7):
        super().__init__()
        self.epsilon = epsilon

    @staticmethod
    def forward(x: torch.Tensor) -> torch.Tensor:
        return torch.tanh(x)

    @staticmethod
    def atanh(x: torch.Tensor) -> torch.Tensor:
        return 0.5 * (x.log1p() - (-x).log1p())

    @staticmethod
    def inverse(y: torch.Tensor) -> torch.Tensor:
        eps = torch.finfo(y.dtype).eps
        return TanhBijector.atanh(y.clamp(min=-1.0 + eps, max=1.0 - eps))

    def log_prob_correction(self, x: torch.Tensor) -> torch.Tensor:
        return torch.log(1.0 - torch.tanh(x) ** 2 + self.epsilon)


# https://github.com/openai/baselines/blob/master/baselines/common/segment_tree.py
class SegmentTree:
    def __init__(self, capacity: int, operation: Callable, init_value: float):
        self.capacity = capacity
        self.tree = [init_value for _ in range(2 * capacity)]
        self.operation = operation

    def _operate_helper(self, start: int, end: int, node: int, node_start: int, node_end: int) -> float:
        if start == node_start and end == node_end:
            return self.tree[node]
        mid = (node_start + node_end) // 2
        if end <= mid:
            return self._operate_helper(start, end, 2 * node, node_start, mid)
        else:
            if mid + 1 <= start:
                return self._operate_helper(start, end, 2 * node + 1, mid + 1, node_end)
            else:
                return self.operation(
                    self._operate_helper(start, mid, 2 * node, node_start, mid),
                    self._operate_helper(mid + 1, end, 2 * node + 1, mid + 1, node_end),
                )

    def operate(self, start: int = 0, end: int = 0) -> float:
        if end <= 0:
            end += self.capacity
        end -= 1

        return self._operate_helper(start, end, 1, 0, self.capacity - 1)

    def __setitem__(self, idx: int, val: float):
        idx += self.capacity
        self.tree[idx] = val

        idx //= 2
        while idx >= 1:
            self.tree[idx] = self.operation(self.tree[2 * idx], self.tree[2 * idx + 1])
            idx //= 2

    def __getitem__(self, idx: int) -> float:
        return self.tree[self.capacity + idx]


# https://github.com/openai/baselines/blob/master/baselines/common/segment_tree.py
class SumSegmentTree(SegmentTree):
    def __init__(self, capacity: int):
        super(SumSegmentTree, self).__init__(capacity=capacity, operation=operator.add, init_value=0.0)

    def sum(self, start: int = 0, end: int = 0) -> float:
        return super(SumSegmentTree, self).operate(start, end)

    def retrieve(self, upperbound: float) -> int:
        idx = 1
        while idx < self.capacity:
            left = 2 * idx
            right = left + 1
            if self.tree[left] > upperbound:
                idx = 2 * idx
            else:
                upperbound -= self.tree[left]
                idx = right
        return idx - self.capacity


# https://github.com/openai/baselines/blob/master/baselines/common/segment_tree.py
class MinSegmentTree(SegmentTree):
    def __init__(self, capacity: int):
        super(MinSegmentTree, self).__init__(capacity=capacity, operation=min, init_value=float("inf"))

    def min(self, start: int = 0, end: int = 0) -> float:
        return super(MinSegmentTree, self).operate(start, end)
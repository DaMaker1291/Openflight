"""DisturbanceObserver example (12 -> 64 -> 64 -> 3), matches spec section 2."""
import torch
import torch.nn as nn


class DisturbanceObserver(nn.Module):
    def __init__(self):
        super().__init__()
        self.network = nn.Sequential(
            nn.Linear(12, 64), nn.ReLU(),
            nn.Linear(64, 64), nn.ReLU(),
            nn.Linear(64, 3))

    def forward(self, x):
        return self.network(x)


def make_weights(path="examples/mlp_observer/model_weights.pt", seed=0):
    torch.manual_seed(seed)
    m = DisturbanceObserver()
    torch.save({k: v.cpu() for k, v in m.state_dict().items()}, path)
    print(f"wrote {path}")


if __name__ == "__main__":
    make_weights()

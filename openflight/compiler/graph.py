"""Computational graph extraction via torch.fx + Sequential fallback."""
from __future__ import annotations

from dataclasses import dataclass, field

import torch
import torch.nn as nn

SUPPORTED = {"linear", "relu", "tanh", "sigmoid"}


@dataclass
class Node:
    operation: str  # linear | relu | tanh | sigmoid
    inputs: list
    attributes: dict = field(default_factory=dict)
    output_shape: tuple = ()
    name: str = ""


@dataclass
class Graph:
    nodes: list[Node]
    input_shape: tuple
    output_shape: tuple
    param_count: int = 0


def _seq_to_graph(model: nn.Sequential, example_input: torch.Tensor) -> Graph:
    nodes: list[Node] = []
    # infer shapes by tracing tensor
    x = example_input
    idx = 0
    li = 0
    for mod in model:
        if isinstance(mod, nn.Linear):
            if mod.bias is None:
                raise ValueError(
                    "Linear without bias is not supported; use nn.Linear(..., bias=True)")
            w, b = mod.weight.detach(), mod.bias.detach()
            out = x @ w.T + b
            nodes.append(Node("linear", inputs=[f"t{idx}"],
                              attributes={"weight": w.clone(), "bias": b.clone()},
                              output_shape=tuple(out.shape), name=f"linear{li}"))
            li += 1
            idx += 1
            x = out
        elif isinstance(mod, nn.ReLU):
            x = torch.relu(x)
            nodes.append(Node("relu", inputs=[f"t{idx - 1}"],
                              output_shape=tuple(x.shape), name=f"relu{idx}"))
        elif isinstance(mod, nn.Tanh):
            x = torch.tanh(x)
            nodes.append(Node("tanh", inputs=[f"t{idx - 1}"],
                              output_shape=tuple(x.shape), name=f"tanh{idx}"))
        elif isinstance(mod, nn.Sigmoid):
            x = torch.sigmoid(x)
            nodes.append(Node("sigmoid", inputs=[f"t{idx - 1}"],
                              output_shape=tuple(x.shape), name=f"sigmoid{idx}"))
        else:
            raise ValueError(
                f"unsupported module {type(mod).__name__}; supported: "
                "Linear, ReLU, Tanh, Sigmoid")
    # rewire inputs sequentially
    for k in range(1, len(nodes)):
        nodes[k].inputs = [f"t{k - 1}"]
    nodes[0].inputs = ["input"]
    params = sum(n.attributes["weight"].numel() + n.attributes["bias"].numel()
                 for n in nodes if n.operation == "linear")
    return Graph(nodes, tuple(example_input.shape), tuple(x.shape), params)


def extract_graph(model: nn.Module, example_input: torch.Tensor) -> Graph:
    """Try torch.fx symbolic trace; fall back to Sequential walk.

    FX gives op order + shapes for general small MLPs; the Sequential path
    handles the common case deterministically.
    """
    model.eval()
    if isinstance(model, nn.Sequential):
        return _seq_to_graph(model, example_input)
    # Generic: attempt FX trace and map call_module nodes
    try:
        import torch.fx as fx

        tracemod = fx.symbolic_trace(model)
        # collect submodule types in execution order
        seq_nodes: list[Node] = []
        x = example_input
        with torch.no_grad():
            for node in tracemod.graph.nodes:
                if node.op == "placeholder":
                    continue
                if node.op == "call_module":
                    sub = dict(tracemod.named_modules())[node.target]
                    if isinstance(sub, nn.Linear):
                        if sub.bias is None:
                            raise ValueError(
                                f"Linear without bias at {node.target} is not "
                                "supported; use bias=True")
                        w, b = sub.weight.detach(), sub.bias.detach()
                        out = x @ w.T + b
                        seq_nodes.append(Node("linear", inputs=["x"],
                                              attributes={"weight": w.clone(),
                                                          "bias": b.clone()},
                                              output_shape=tuple(out.shape),
                                              name=str(node.target)))
                        x = out
                    elif isinstance(sub, nn.ReLU):
                        x = torch.relu(x)
                        seq_nodes.append(Node("relu", inputs=["x"],
                                              output_shape=tuple(x.shape),
                                              name=str(node.target)))
                    elif isinstance(sub, nn.Tanh):
                        x = torch.tanh(x)
                        seq_nodes.append(Node("tanh", inputs=["x"],
                                              output_shape=tuple(x.shape),
                                              name=str(node.target)))
                    elif isinstance(sub, nn.Sigmoid):
                        x = torch.sigmoid(x)
                        seq_nodes.append(Node("sigmoid", inputs=["x"],
                                              output_shape=tuple(x.shape),
                                              name=str(node.target)))
                    else:
                        raise ValueError(
                            f"unsupported operator {type(sub).__name__} "
                            f"at {node.target}")
                elif node.op in ("call_function", "call_method"):
                    raise ValueError(
                        f"unsupported functional op {node.target}; use nn.Linear/"
                        "ReLU/Tanh/Sigmoid modules")
        params = sum(n.attributes["weight"].numel() + n.attributes["bias"].numel()
                     for n in seq_nodes if n.operation == "linear")
        return Graph(seq_nodes, tuple(example_input.shape), tuple(x.shape), params)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(
            f"graph extraction failed ({e}); supply model as nn.Sequential of "
            "Linear/ReLU/Tanh/Sigmoid") from e

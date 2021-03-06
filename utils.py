# -*- coding: utf-8 -*-
"""
Created on Fri Apr  2 10:51:30 2021

@author: sxp
"""
import json
import numpy as np
import pandas as pd
from scipy import sparse
from texttable import Texttable
from sklearn.decomposition import TruncatedSVD, KernelPCA
from sklearn.metrics import roc_auc_score, f1_score
import torch
import scipy
from torch_sparse import coalesce
from tensorboardX import SummaryWriter
import datetime

def read_graph(args):
    """
    :param args: Arguments object.
    :return edges: Edges dictionary.
    """
    if 'bitcoin' in args.edge_path:
        dataset = pd.read_csv(args.edge_path).values.tolist()
    else:
        dataset = pd.read_csv(args.edge_path, sep='\t').values.tolist()
    edges = {}
    edges["positive_edges"] = [edge[0:2] for edge in dataset if edge[2] == 1]
    edges["negative_edges"] = [edge[0:2] for edge in dataset if edge[2] == -1]
    edges["ecount"] = len(dataset)
    edges["ncount"] = max(len(set([edge[0] for edge in dataset]+[edge[1] for edge in dataset])), max(dataset)[0]+1)
    return edges

def tab_printer(args):
    """
    Print the logs in a nice tabular format.
    :param args: Parameters used for the model.
    """
    args = vars(args)
    keys = sorted(args.keys())
    t = Texttable()
    t.add_rows([["Parameter", "Value"]])
    t.add_rows([[k.replace("_", " ").capitalize(), args[k]] for k in keys])
    print(t.draw())

def calculate_auc(targets, predictions, edges):
    neg_ratio = len(edges["negative_edges"])/edges["ecount"]
    targets_rev = [0 if target == 1 else 1 for target in targets] # turn the first indicator (1) to positive
    auc = roc_auc_score(targets_rev, predictions[:, 0])
    f1_micro = f1_score(targets_rev, [1 if p > neg_ratio else 0 for p in predictions[:, 0]], average='micro')
    f1 = f1_score(targets_rev, [1 if p > neg_ratio else 0 for p in predictions[:, 0]])
    f1_macro = f1_score(targets_rev, [1 if p > neg_ratio else 0 for p in predictions[:, 0]], average='macro')
    # f1 = f1_score(targets, np.argmax(predictions, axis=1))
    return auc, f1_micro, f1, f1_macro

def score_printer(logs):
    """
    Print the performance for every 10th epoch on the test dataset.
    :param logs: Log dictionary.
    """
    t = Texttable()
    t.add_rows([per[:3] for i, per in enumerate(logs["performance"]) if i % 10 == 0])
    print(t.draw())

def save_logs(args, logs):
    """
    Save the logs at the path.
    :param args: Arguments objects.
    :param logs: Log dictionary.
    """
    writer=SummaryWriter("./log")
    for i, item in enumerate(logs["performance"]):
        if i > 0:
            writer.add_scalar('AUC', item[1], item[0])
            writer.add_scalar('F1_micro', item[2], item[0])
            writer.add_scalar('F1', item[3], item[0])
            writer.add_scalar('F1_macro', item[4], item[0])
            writer.add_scalar('Loss', logs["loss"][i-1], item[0])
    writer.close()


def setup_features(args, positive_edges, negative_edges, node_count):
    """
    Setting up the node features as a numpy array.
    :param args: Arguments object.
    :param positive_edges: Positive edges list.
    :param negative_edges: Negative edges list.
    :param node_count: Number of nodes.
    :return X: Node features.
    """
    if args.spectral_features:
        X = create_spectral_features(args, positive_edges, negative_edges, node_count)
    else:
        X = create_general_features(args)
    return X

def create_general_features(args):
    """
    Reading features using the path.
    :param args: Arguments object.
    :return X: Node features.
    """
    X = np.array(pd.read_csv(args.features_path))
    return X

def create_spectral_features(args, pos_edge_index, neg_edge_index,
                             num_nodes=None):
    """Creates :obj:`in_channels` spectral node features based on
    positive and negative edges.

    Args:
        pos_edge_index (LongTensor): The positive edge indices.
        neg_edge_index (LongTensor): The negative edge indices.
        num_nodes (int, optional): The number of nodes, *i.e.*
            :obj:`max_val + 1` of :attr:`pos_edge_index` and
            :attr:`neg_edge_index`. (default: :obj:`None`)
    """
    pos_edge_index = torch.tensor(pos_edge_index).t().long()
    neg_edge_index = torch.tensor(neg_edge_index).t().long()
    edge_index = torch.cat([pos_edge_index, neg_edge_index], dim=1)
    N = edge_index.max().item() + 1 if num_nodes is None else num_nodes
    edge_index = edge_index.to(torch.device('cpu')).long()

    pos_val = torch.full((pos_edge_index.size(1), ), 2, dtype=torch.float)
    neg_val = torch.full((neg_edge_index.size(1), ), 0, dtype=torch.float)
    val = torch.cat([pos_val, neg_val], dim=0)

    row, col = edge_index
    edge_index = torch.cat([edge_index, torch.stack([col, row])], dim=1)
    val = torch.cat([val, val], dim=0)

    edge_index, val = coalesce(edge_index, val, N, N)
    val = val - 1

    edge_index = edge_index.detach().numpy()
    val = val.detach().numpy()
    A = scipy.sparse.coo_matrix((val, edge_index), shape=(N, N))
    svd = TruncatedSVD(n_components=args.reduction_dimensions,
                           n_iter=args.reduction_iterations,
                           random_state=args.seed)
    svd.fit(A)
    x = svd.components_.T
    return torch.from_numpy(x).to(torch.float).to(pos_edge_index.device)


'''
Math functions for Hyperbolic
'''


def cosh(x, clamp=15):
    return x.clamp(-clamp, clamp).cosh()


def sinh(x, clamp=15):
    return x.clamp(-clamp, clamp).sinh()


def tanh(x, clamp=15):
    return x.clamp(-clamp, clamp).tanh()


def arcosh(x):
    return Arcosh.apply(x)


def arsinh(x):
    return Arsinh.apply(x)


def artanh(x):
    return Artanh.apply(x)


class Artanh(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x):
        x = x.clamp(-1 + 1e-15, 1 - 1e-15)
        ctx.save_for_backward(x)
        z = x.double()
        return (torch.log_(1 + z).sub_(torch.log_(1 - z))).mul_(0.5).to(x.dtype)

    @staticmethod
    def backward(ctx, grad_output):
        input, = ctx.saved_tensors
        return grad_output / (1 - input ** 2)


class Arsinh(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x):
        ctx.save_for_backward(x)
        z = x.double()
        return (z + torch.sqrt_(1 + z.pow(2))).clamp_min_(1e-15).log_().to(x.dtype)

    @staticmethod
    def backward(ctx, grad_output):
        input, = ctx.saved_tensors
        return grad_output / (1 + input ** 2) ** 0.5


class Arcosh(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x):
        x = x.clamp(min=1.0 + 1e-15)
        ctx.save_for_backward(x)
        z = x.double()
        z = (z + torch.sqrt_(z.pow(2) - 1)).clamp_min_(1e-15).log_().to(x.dtype)
        return z

    @staticmethod
    def backward(ctx, grad_output):
        input, = ctx.saved_tensors
        return grad_output / (input ** 2 - 1) ** 0.5

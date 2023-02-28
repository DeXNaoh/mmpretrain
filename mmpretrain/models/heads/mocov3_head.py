# Copyright (c) OpenMMLab. All rights reserved.
import torch
import torch.nn as nn
from mmengine.dist import get_rank

from mmpretrain.registry import MODELS
from mmpretrain.utils import concat_all_gather
from .base_head import BaseHead


@MODELS.register_module()
class MoCoV3Head(BaseHead):
    """Head for MoCo v3 algorithms.

    This head builds a predictor, which can be any registered neck component.
    It also implements latent contrastive loss between two forward features.
    Part of the code is modified from:
    `<https://github.com/facebookresearch/moco-v3/blob/main/moco/builder.py>`_.

    Args:
        predictor (dict): Config dict for module of predictor.
        loss (dict): Config dict for module of loss functions.
        temperature (float): The temperature hyper-parameter that
            controls the concentration level of the distribution.
            Defaults to 1.0.
    """

    def __init__(self,
                 predictor: dict,
                 loss: dict,
                 temperature: float = 1.0) -> None:
        super().__init__()
        self.predictor = MODELS.build(predictor)
        self.loss_module = MODELS.build(loss)
        self.temperature = temperature

    def loss(self, base_out: torch.Tensor,
             momentum_out: torch.Tensor) -> torch.Tensor:
        """Forward head.

        Args:
            base_out (torch.Tensor): NxC features from base_encoder.
            momentum_out (torch.Tensor): NxC features from momentum_encoder.

        Returns:
            torch.Tensor: The loss tensor.
        """
        # predictor computation
        pred = self.predictor([base_out])[0]

        # normalize
        pred = nn.functional.normalize(pred, dim=1)
        target = nn.functional.normalize(momentum_out, dim=1)

        # get negative samples
        target = concat_all_gather(target)

        # Einstein sum is more intuitive
        logits = torch.einsum('nc,mc->nm', [pred, target]) / self.temperature

        # generate labels
        batch_size = logits.shape[0]
        labels = (torch.arange(batch_size, dtype=torch.long) +
                  batch_size * get_rank()).to(logits.device)

        loss = self.loss_module(logits, labels)
        return loss
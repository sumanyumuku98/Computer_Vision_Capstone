"""
Copyright (C) 2019 NVIDIA Corporation.  All rights reserved.
Licensed under the CC BY-NC-SA 4.0 license (https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode).
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from models.networks.architecture import VGG19
from models.networks.vgg_fix import VGG19_feature_color_torchversion

# Defines the GAN loss which uses either LSGAN or the regular GAN.
# When LSGAN is used, it is basically same as MSELoss,
# but it abstracts away the need to create the target label tensor
# that has the same size as the input
class GANLoss(nn.Module):
    def __init__(self, gan_mode, target_real_label=1.0, target_fake_label=0.0,
                 tensor=torch.FloatTensor, opt=None):
        super(GANLoss, self).__init__()
        self.real_label = target_real_label
        self.fake_label = target_fake_label
        self.real_label_tensor = None
        self.fake_label_tensor = None
        self.zero_tensor = None
        self.Tensor = tensor
        self.gan_mode = gan_mode
        self.opt = opt
        if gan_mode == 'ls':
            pass
        elif gan_mode == 'original':
            pass
        elif gan_mode == 'w':
            pass
        elif gan_mode == 'hinge':
            pass
        else:
            raise ValueError('Unexpected gan_mode {}'.format(gan_mode))

    def get_target_tensor(self, input, target_is_real):
        if target_is_real:
            if self.real_label_tensor is None:
                self.real_label_tensor = self.Tensor(1).fill_(self.real_label)
                self.real_label_tensor.requires_grad_(False)
            return self.real_label_tensor.expand_as(input)
        else:
            if self.fake_label_tensor is None:
                self.fake_label_tensor = self.Tensor(1).fill_(self.fake_label)
                self.fake_label_tensor.requires_grad_(False)
            return self.fake_label_tensor.expand_as(input)

    def get_zero_tensor(self, input):
        if self.zero_tensor is None:
            self.zero_tensor = self.Tensor(1).fill_(0)
            self.zero_tensor.requires_grad_(False)
        return self.zero_tensor.expand_as(input)

    def loss(self, input, target_is_real, for_discriminator=True):
        if self.gan_mode == 'original':  # cross entropy loss
            target_tensor = self.get_target_tensor(input, target_is_real)
            loss = F.binary_cross_entropy_with_logits(input, target_tensor)
            return loss
        elif self.gan_mode == 'ls':
            target_tensor = self.get_target_tensor(input, target_is_real)
            return F.mse_loss(input, target_tensor)
        elif self.gan_mode == 'hinge':
            if for_discriminator:
                if target_is_real:
                    minval = torch.min(input - 1, self.get_zero_tensor(input))
                    loss = -torch.mean(minval)
                else:
                    minval = torch.min(-input - 1, self.get_zero_tensor(input))
                    loss = -torch.mean(minval)
            else:
                assert target_is_real, "The generator's hinge loss must be aiming for real"
                loss = -torch.mean(input)
            return loss
        else:
            # wgan
            if target_is_real:
                return -input.mean()
            else:
                return input.mean()

    def __call__(self, input, target_is_real, for_discriminator=True):
        # computing loss is a bit complicated because |input| may not be
        # a tensor, but list of tensors in case of multiscale discriminator
        if isinstance(input, list):
            loss = 0
            for pred_i in input:
                if isinstance(pred_i, list):
                    pred_i = pred_i[-1]
                loss_tensor = self.loss(pred_i, target_is_real, for_discriminator)
                bs = 1 if len(loss_tensor.size()) == 0 else loss_tensor.size(0)
                new_loss = torch.mean(loss_tensor.view(bs, -1), dim=1)
                loss += new_loss
            return loss / len(input)
        else:
            return self.loss(input, target_is_real, for_discriminator)


# Perceptual loss that uses a pretrained VGG network
class VGGLoss(nn.Module):
    def __init__(self, gpu_ids):
        super(VGGLoss, self).__init__()
        self.vgg = VGG19().cuda()
        self.criterion = nn.L1Loss()
        self.weights = [1.0 / 32, 1.0 / 16, 1.0 / 8, 1.0 / 4, 1.0]

    def forward(self, x, y):
        x_vgg, y_vgg = self.vgg(x), self.vgg(y)
        loss = 0
        for i in range(len(x_vgg)):
            loss += self.weights[i] * self.criterion(x_vgg[i], y_vgg[i].detach())
        return loss

# VGG-based losses that uses a pretrained VGG network
class VGGLosses(nn.Module):
    def __init__(self, gpu_ids):
        super(VGGLosses, self).__init__()
        self.vgg = VGG19().cuda()
        self.l1 = nn.L1Loss()
        self.l2 = nn.MSELoss()
        self.weights = [1.0 / 32, 1.0 / 16, 1.0 / 8, 1.0 / 4, 1.0]

    def compute_gram(self, x):
        b, ch, h, w = x.size()
        f = x.view(b, ch, w * h)
        f_T = f.transpose(1, 2)
        G = f.bmm(f_T) / (h * w * ch)

        return G

    def forward(self, x, y):
        x_vgg, y_vgg = self.vgg(x), self.vgg(y)
        fm_loss = 0.0
        for i in range(len(x_vgg)):
            fm_loss += self.weights[i] * self.l1(x_vgg[i], y_vgg[i].detach())

        style_loss = 0.0
        for i in range(len(x_vgg)):
            style_loss += self.l1(self.compute_gram(x_vgg[i]), self.compute_gram(y_vgg[i].detach()))

        perc_loss = self.l2(x_vgg[-2], y_vgg[-2].detach())

        return fm_loss, style_loss, perc_loss

class VGGLosses_fix(nn.Module):
    def __init__(self, vgg_normal_correct):
        super(VGGLosses_fix, self).__init__()
        self.vggnet_fix = VGG19_feature_color_torchversion(vgg_normal_correct=vgg_normal_correct)
        self.vggnet_fix.load_state_dict(torch.load('models/vgg19_conv.pth'))
        self.vggnet_fix.eval()
        for param in self.vggnet_fix.parameters():
            param.requires_grad = False

        self.vggnet_fix = self.vggnet_fix.cuda()
        self.l1 = nn.L1Loss()
        self.l2 = nn.MSELoss()
        self.weights = [1.0 / 32, 1.0 / 16, 1.0 / 8, 1.0 / 4, 1.0]

    def compute_gram(self, x):
        b, ch, h, w = x.size()
        f = x.view(b, ch, w * h)
        f_T = f.transpose(1, 2)
        G = f.bmm(f_T) / (h * w * ch)

        return G

    def forward(self, x, y):
        x_vgg = self.vggnet_fix(x, ['r12', 'r22', 'r32', 'r42', 'r52'], preprocess=True)
        y_vgg = self.vggnet_fix(y, ['r12', 'r22', 'r32', 'r42', 'r52'], preprocess=True)
        fm_loss = 0.0
        for i in range(len(x_vgg)):
            fm_loss += self.weights[i] * self.l1(x_vgg[i], y_vgg[i].detach())

        style_loss = 0.0
        for i in range(len(x_vgg)):
            style_loss += self.l1(self.compute_gram(x_vgg[i]), self.compute_gram(y_vgg[i].detach()))

        perc_loss = self.l2(x_vgg[-2], y_vgg[-2].detach())

        return fm_loss, style_loss, perc_loss

# KL Divergence loss used in VAE with an image encoder
class KLDLoss(nn.Module):
    def forward(self, mu, logvar):
        return -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp())

class TV_Loss(nn.Module):
    def forward(self, x):
        """
        Compute total variation loss.
        Inputs:
        - img: PyTorch Variable of shape (1, 3, H, W) holding an input image.
        - tv_weight: Scalar giving the weight w_t to use for the TV loss.
        Returns:
        - loss: PyTorch Variable holding a scalar giving the total variation loss
        for img weighted by tv_weight.
        """
        b, c, h, w = x.shape
        w_variance = torch.sum(torch.pow(x[:,:,:,:-1] - x[:,:,:,1:], 2)) / (c)
        h_variance = torch.sum(torch.pow(x[:,:,:-1,:] - x[:,:,1:,:], 2))
        tv_loss = h_variance + w_variance
        return tv_loss


#!/usr/bin/env python3
"""Keep directly scanned framebuffer addresses within the DPU register width."""
from pathlib import Path


def apply(kernel):
    path = Path(kernel) / 'drivers/unisoc_platform/sprd_disp/sprd_drm.c'
    text = path.read_text()
    old = 'dma_set_mask_and_coherent(&pdev->dev, ~0)'
    new = 'dma_set_mask_and_coherent(&pdev->dev, DMA_BIT_MASK(32))'
    if new not in text:
        if text.count(old) != 1:
            raise ValueError('Unexpected display DMA mask')
        path.write_text(text.replace(old, new))
    # Include the full DMA address in allocation diagnostics to distinguish a
    # valid CPU mapping from an address the 32-bit scanout engine can reach.
    path = Path(kernel) / 'drivers/unisoc_platform/sprd_disp/sprd_gem.c'
    text = path.read_text()
    old = ('DRM_INFO("args->pitch:%u args->size:%llu vaddr:0x%px\\n",\n'
           '              args->pitch, args->size, sprd_gem->vaddr);')
    new = ('DRM_INFO("args->pitch:%u args->size:%llu vaddr:0x%px dma:%pad\\n",\n'
           '              args->pitch, args->size, sprd_gem->vaddr, &sprd_gem->dma_addr);')
    if new not in text:
        if text.count(old) != 1:
            raise ValueError('Unexpected GEM allocation log')
        path.write_text(text.replace(old, new))

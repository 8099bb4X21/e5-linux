"""Wire the vendor SPRD host DMA backend into the upstream host scheduler."""
from pathlib import Path


def apply(kernel):
    path = kernel / 'drivers/usb/musb/musb_host.c'
    text = path.read_text()
    text = text.replace('/* SPRD host DMA is not wired into this host scheduler. */\n\t', '')
    text = text.replace('use_dma = !musb_dma_sprd(musb);', 'use_dma = 1;')
    if '#include "board-musb-sprd-host.h"' not in text:
        text = text.replace('static bool musb_tx_dma_program(',
                            '#include "board-musb-sprd-host.h"\n\nstatic bool musb_tx_dma_program(', 1)
        start = text.index('static bool musb_tx_dma_program(')
        end = text.index('\n/*\n * Program an HDRC endpoint', start)
        body = text[start:end]
        body = body.replace('\telse\n\t\treturn false;',
            '\telse if (musb_dma_sprd(hw_ep->musb)) {\n'
            '\t\tchannel->actual_len = 0;\n'
            '\t\tmode = !!(urb->transfer_flags & URB_ZERO_PACKET);\n'
            '\t} else\n\t\treturn false;', 1)
        body = body.replace('if (!dma->channel_program(', 'if (dma->channel_program(', 1)
        body = body.replace('urb->transfer_dma + offset, length)) {',
                            'urb->transfer_dma + offset, length) <= 0) {', 1)
        body = body.replace('\t\tdma->channel_release(channel);',
            '\t\tif (channel->status == MUSB_DMA_STATUS_BUSY)\n'
            '\t\t\tdma->channel_abort(channel);\n'
            '\t\tdma->channel_release(channel);', 1)
        body = body.replace('\treturn true;',
            '\tif (musb_dma_sprd(hw_ep->musb))\n\t\tmusb_sprd_tx_start(hw_ep);\n'
            '\treturn true;', 1)
        text = text[:start] + body + text[end:]
        start = text.rindex('static void musb_ep_program(struct musb *musb, u8 epnum,')
        end = text.index('\n/* Schedule next QH', start)
        body = text[start:end]
        # SPRD completion can precede final FIFO drain. Preserve CSR/toggle
        # state between descriptors instead of flushing the previous packet.
        a = body.index('\t\t\t/* flush all old state, set default */')
        b = body.index('\n\t\t} else {\n\t\t\t/* endpoint 0', a)
        block = body[a:b]
        body = body[:a] + '\t\t\tif (!musb_dma_sprd(musb)) {\n' + ''.join(
            '\t' + line + '\n' for line in block.splitlines()) + '\t\t\t}' + body[b:]
        marker = '\t\tif (hw_ep->rx_reinit) {'
        addition = ('\t\tif (musb_dma_sprd(musb) && dma_channel) {\n'
            '\t\t\tif (musb_sprd_rx_program(dma_channel, musb, epnum,\n'
            '\t\t\t\t\tqh, urb, offset, len))\n\t\t\t\treturn;\n'
            '\t\t\tdma_channel = NULL;\n\t\t}\n\n')
        assert body.count(marker) == 1
        body = body.replace(marker, addition + marker, 1)
        text = text[:start] + body + text[end:]
        # Let the controller maintain bulk toggles between DMA descriptors.
        start = text.index('static void musb_advance_schedule(')
        end = text.index('static u16 musb_h_flush_rxfifo', start)
        body = text[start:end]
        body = body.replace('case USB_ENDPOINT_XFER_BULK:\n\tcase USB_ENDPOINT_XFER_INT:',
            'case USB_ENDPOINT_XFER_BULK:\n\t\tif (musb_dma_sprd(musb))\n'
            '\t\t\tbreak;\n\t\tfallthrough;\n\tcase USB_ENDPOINT_XFER_INT:', 1)
        # Completion drops the lock; callbacks may have removed the queue.
        body = body.replace('\tmusb_giveback(musb, urb, status);\n\tqh->is_ready = ready;',
                            '\tmusb_giveback(musb, urb, status);', 1)
        body = body.replace('\tqh = musb_ep_get_qh(hw_ep, is_in);',
                            '\tqh = musb_ep_get_qh(hw_ep, is_in);\n'
                            '\tif (qh)\n\t\tqh->is_ready = ready;', 1)
        text = text[:start] + body + text[end:]
        text = text.replace('\tmusb->hops.tx_dma_program = musb_tx_dma_program;',
            '\tmusb->hops.tx_dma_program = musb_tx_dma_program;\n'
            '\tmusb->hops.rx_dma_program = musb_sprd_rx_next;', 1)
        text = text.replace('Only the two functions that exist in this tree are wired up -\n'
            '\t * hops.host_start and hops.rx_dma_program have no implementation here\n'
            '\t * and stay NULL, so every caller has to test for that.',
            'RX/TX DMA and completion are wired up here. hops.host_start\n'
            '\t * remains optional; the platform initializes the host controller.')
    path.write_text(text)
    (path.parent / 'board-musb-sprd-host.h').write_bytes(
        Path(__file__).with_name('musb-sprd-host.h').read_bytes())

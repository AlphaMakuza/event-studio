"""Bounds-checked ECF event decompression, without an external HDF5 plugin.

Adapted from Prophesee's hdf5_ecf/ecf_codec.cpp (Copyright Prophesee S.A.),
licensed under Apache-2.0. This Python adaptation adds input bounds and run
validation and NumPy unpacking. See release-docs/legal/HDF5-ECF-LICENSE.txt.
"""
import struct
import numpy as np


def decode_ecf(data, expected_count):
    position = 0

    def read(fmt):
        nonlocal position
        size = struct.calcsize(fmt)
        if position + size > len(data):
            raise ValueError('Truncated ECF event chunk.')
        value = struct.unpack_from(fmt, data, position)[0]
        position += size
        return value

    info = read('<I')
    count = info >> 2
    if not 0 < count <= 65535 or count != expected_count:
        raise ValueError('ECF event count does not match the HDF5 chunk.')
    t = np.empty(count, dtype=np.int64)
    current = read('<Q')
    i = 0
    while i < count:
        value = read('<B')
        delta, run = value >> 4, value & 15
        if delta == 15:
            shift, delta = 0, 0
            while value >> 4 == 15:
                if shift >= 64:
                    raise ValueError('Invalid ECF timestamp delta.')
                delta |= (value & 15) << shift
                shift += 4
                value = read('<B')
            # The terminator is also the next timestamp run header.
            position -= 1
            current += delta
            continue
        current += delta
        if current >= np.iinfo(np.int64).max:
            raise ValueError('ECF timestamp exceeds the supported int64 range.')
        if run == 15:
            run = read('<H')
        if not 0 < run <= count - i:
            raise ValueError('Invalid ECF timestamp run length.')
        t[i:i + run] = current
        i += run

    def runs(dtype, fmt, shift, mask):
        output = np.empty(count, dtype=dtype)
        i = 0
        while i < count:
            value = read(fmt)
            run = value & mask
            if run == mask:
                run = read('<H')
            if not 0 < run <= count - i:
                raise ValueError('Invalid ECF spatial/polarity run length.')
            output[i:i + run] = value >> shift
            i += run
        return output

    def packed(bits):
        nonlocal position
        groups = (count + 3) // 4
        dtype, size = ('<u4', 12) if bits == 24 else ('<u2', 6)
        if position + groups * size > len(data):
            raise ValueError('Truncated packed ECF coordinates.')
        words = np.frombuffer(data, dtype=dtype, count=groups * 3, offset=position).reshape(-1, 3)
        words = words.astype(np.uint32)
        values = np.empty((groups, 4), dtype=np.uint32)
        if bits == 24:
            values[:, 0] = words[:, 0] >> 8
            values[:, 1] = (words[:, 0] & 255) | ((words[:, 1] >> 16) << 8)
            values[:, 2] = (words[:, 1] & 65535) | ((words[:, 2] >> 24) << 16)
            values[:, 3] = words[:, 2] & 0xffffff
        else:
            values[:, 0] = words[:, 0] >> 4
            values[:, 1] = (words[:, 0] & 15) | ((words[:, 1] >> 8) << 4)
            values[:, 2] = (words[:, 1] & 255) | ((words[:, 2] >> 12) << 8)
            values[:, 3] = words[:, 2] & 4095
        position += groups * size
        return values.ravel()[:count]

    if info & 2:
        values = packed(24)
        y = ((values >> 12) & 2047).astype(np.int32)
        x = ((values >> 1) & 2047).astype(np.int32)
        p = (values & 1).astype(np.int8)
    else:
        y = runs(np.int32, '<H', 5, 31)
        if info & 1:
            values = packed(12)
            x, p = (values >> 1).astype(np.int32), (values & 1).astype(np.int8)
        else:
            x = np.empty(count, dtype=np.int32)
            i = 0
            while i < count:
                value = read('<H')
                values = [value >> 5] + [(value >> 5) + j + 1 for j in range(5) if value & (1 << (4 - j))]
                # Upstream pads the final masked group by up to five values.
                length = min(len(values), count - i)
                x[i:i + length] = values[:length]
                i += length
            p = runs(np.int8, '<B', 7, 127)
    if position != len(data):
        raise ValueError('Unexpected trailing bytes in ECF event chunk.')
    return t, x, y, p

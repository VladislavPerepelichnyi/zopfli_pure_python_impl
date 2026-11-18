"""Minimal DEFLATE walker used by the tests to read block types (BTYPE).

Test-only (the package itself never inflates). Decodes each block fully so it
can find the next block header.
"""

_LBASE = [3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
          67, 83, 99, 115, 131, 163, 195, 227, 258]
_LEXT = [0] * 8 + [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4 + [5] * 4 + [0]
_DBASE = [1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513,
          769, 1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577]
_DEXT = [0, 0, 0, 0] + [i // 2 for i in range(2, 28)]


class _Bits:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def bit(self):
        b = (self.data[self.pos >> 3] >> (self.pos & 7)) & 1
        self.pos += 1
        return b

    def bits(self, n):
        v = 0
        for i in range(n):
            v |= self.bit() << i
        return v


def _table(lengths):
    codes = {}
    code = 0
    for length in range(1, 16):
        for sym, l in enumerate(lengths):
            if l == length:
                codes[(length, code)] = sym
                code += 1
        code <<= 1
    return codes


def _decode(br, table):
    code = length = 0
    while True:
        code = (code << 1) | br.bit()
        length += 1
        if (length, code) in table:
            return table[(length, code)]
        if length > 15:
            raise ValueError("bad code")


def block_types(stream):
    br = _Bits(stream)
    types = []
    while True:
        final = br.bit()
        btype = br.bits(2)
        types.append(btype)
        if btype == 0:
            br.pos = (br.pos + 7) & ~7
            n = br.bits(16)
            br.bits(16)
            br.pos += 8 * n
        else:
            if btype == 1:
                ll = [8] * 144 + [9] * 112 + [7] * 24 + [8] * 8
                d = [5] * 30
            else:
                hlit, hdist, hclen = br.bits(5) + 257, br.bits(5) + 1, br.bits(4) + 4
                order = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
                cl = [0] * 19
                for i in range(hclen):
                    cl[order[i]] = br.bits(3)
                ct = _table(cl)
                lens = []
                while len(lens) < hlit + hdist:
                    s = _decode(br, ct)
                    if s < 16:
                        lens.append(s)
                    elif s == 16:
                        lens += [lens[-1]] * (3 + br.bits(2))
                    elif s == 17:
                        lens += [0] * (3 + br.bits(3))
                    else:
                        lens += [0] * (11 + br.bits(7))
                ll, d = lens[:hlit], lens[hlit:]
            lt, dt = _table(ll), _table(d)
            while True:
                s = _decode(br, lt)
                if s == 256:
                    break
                if s > 256:
                    br.bits(_LEXT[s - 257])
                    ds = _decode(br, dt)
                    br.bits(_DEXT[ds])
        if final:
            return types

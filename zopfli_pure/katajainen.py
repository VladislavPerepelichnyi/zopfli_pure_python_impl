"""Port of katajainen.c: length-limited Huffman code lengths.

Bounded package merge algorithm, based on the paper
"A Fast and Space-Economical Algorithm for Length-Limited Coding",
Jyrki Katajainen, Alistair Moffat, Andrew Turpin.

Representation (see docs/notes/tree.md):

* A C ``Node`` (weight, tail, count) is a 3-element Python ``list``
  ``[weight, count, tail]`` (``tail`` is another node or ``None``). Lists are
  used instead of tuples because ``BoundaryPMFinal`` mutates the ``tail`` of an
  existing node, exactly like C.
* The C node pool only hands out fresh nodes and is never garbage collected,
  so it is replaced by plain allocation.
* The leaves (C ``Node`` array sorted by ``qsort``) become two parallel lists:
  ``leaf_weight`` and ``leaf_count`` (the symbol index).
* ``lists[i][0]`` / ``lists[i][1]`` become two parallel lists ``l0[i]`` / ``l1[i]``.
* The recursion of ``BoundaryPM`` is replaced by an explicit stack. The C
  function does no work after its two recursive calls, so a LIFO stack visits
  the lists in exactly the same order.
"""

_W = 0  # Node.weight
_C = 1  # Node.count
_T = 2  # Node.tail

# Leaves whose weight is >= this value make C return an error: the count is
# packed into the low 9 bits of the 64-bit size_t weight for the stable sort.
_MAX_WEIGHT = 1 << (64 - 9)


def _init_node(weight, count, tail):
    """Port of InitNode (katajainen.c). Returns a new node [weight, count, tail]."""
    return [weight, count, tail]


def _boundary_pm(l0, l1, leaf_weight, numsymbols, index):
    """Port of BoundaryPM (katajainen.c).

    Recursion replaced by an explicit stack: BoundaryPM(index - 1) is called
    twice at the very end of the C function, so pushing index - 1 twice onto a
    LIFO stack yields the same depth-first order.
    """
    stack = [index]
    pop = stack.pop
    push = stack.append
    while stack:
        index = pop()
        oldchain = l1[index]
        lastcount = oldchain[1]  # Count of last chain of list.
        if index == 0:
            if lastcount >= numsymbols:
                continue
            l0[0] = oldchain
            # New leaf node in list 0.
            l1[0] = [leaf_weight[lastcount], lastcount + 1, None]
        else:
            l0[index] = oldchain
            prev0 = l0[index - 1]
            prev1 = l1[index - 1]
            s = prev0[0] + prev1[0]
            if lastcount < numsymbols and s > leaf_weight[lastcount]:
                # New leaf inserted in list, so count is incremented.
                l1[index] = [leaf_weight[lastcount], lastcount + 1, oldchain[2]]
            else:
                l1[index] = [s, lastcount, prev1]
                # Two lookahead chains of previous list used up, create new ones.
                push(index - 1)
                push(index - 1)


def _boundary_pm_final(l0, l1, leaf_weight, numsymbols, index):
    """Port of BoundaryPMFinal (katajainen.c)."""
    lastcount = l1[index][1]  # Count of last chain of list.
    s = l0[index - 1][0] + l1[index - 1][0]
    if lastcount < numsymbols and s > leaf_weight[lastcount]:
        # C takes the next (uninitialized) pool node and sets only count and
        # tail; its weight is never read afterwards. Use None for it.
        oldchain = l1[index][2]
        l1[index] = [None, lastcount + 1, oldchain]
    else:
        l1[index][2] = l1[index - 1]


def _init_lists(leaf_weight, maxbits):
    """Port of InitLists (katajainen.c). Returns (l0, l1)."""
    node0 = [leaf_weight[0], 1, None]
    node1 = [leaf_weight[1], 2, None]
    return [node0] * maxbits, [node1] * maxbits


def _extract_bit_lengths(chain, leaf_count, bitlengths):
    """Port of ExtractBitLengths (katajainen.c)."""
    counts = [0] * 16
    end = 16
    ptr = 15
    value = 1

    node = chain
    while node is not None:
        end -= 1
        counts[end] = node[1]
        node = node[2]

    val = counts[15]
    while ptr >= end:
        lim = counts[ptr - 1]
        while val > lim:
            bitlengths[leaf_count[val - 1]] = value
            val -= 1
        ptr -= 1
        value += 1


def length_limited_code_lengths(frequencies, n, maxbits, bitlengths):
    """Port of ZopfliLengthLimitedCodeLengths (katajainen.c).

    Outputs minimum-redundancy length-limited code bitlengths for symbols with
    the given counts. bitlengths (pre-sized list of at least n ints) is filled
    in place. Returns 0 for OK, 1 for error (too few maxbits, or a weight
    >= 2**55).
    """
    # Initialize all bitlengths at 0.
    for i in range(n):
        bitlengths[i] = 0

    # Count used symbols and place them in the leaves.
    used = [i for i in range(n) if frequencies[i]]
    numsymbols = len(used)

    # Check special cases and error conditions.
    if (1 << maxbits) < numsymbols:
        return 1  # Error, too few maxbits to represent symbols.
    if numsymbols == 0:
        return 0  # No symbols at all. OK.
    if numsymbols == 1:
        bitlengths[used[0]] = 1
        return 0  # Only one symbol, give it bitlength 1, not 0. OK.
    if numsymbols == 2:
        bitlengths[used[0]] += 1
        bitlengths[used[1]] += 1
        return 0

    # Sort the leaves from lightest to heaviest. C adds the symbol index into
    # the low 9 bits of the weight ((weight << 9) | count) so that qsort
    # becomes stable, then shifts the weight back. Sorting by that same packed
    # key reproduces the C order (keys are distinct for n <= 512, and for the
    # unreachable n > 512 ties keep the original order like glibc's merge
    # sort). See docs/notes/tree.md for the comparator caveat
    # (docs/UPSTREAM_FINDINGS.md).
    packed = []
    for i in used:
        w = frequencies[i]
        if w >= _MAX_WEIGHT:
            return 1  # Error, we need 9 bits for the count.
        packed.append(((w << 9) | i, i))
    packed.sort()
    leaf_weight = [p[0] >> 9 for p in packed]
    leaf_count = [p[1] for p in packed]

    if numsymbols - 1 < maxbits:
        maxbits = numsymbols - 1
    if maxbits > 15:
        # C's ExtractBitLengths has a 16-entry counts[] array; a chain of 16 or
        # more lists reads/writes out of bounds (undefined behaviour). Zopfli
        # only uses maxbits 15 and 7.
        raise ValueError("maxbits > 15 with more than 16 used symbols is "
                         "undefined behaviour in ZopfliLengthLimitedCodeLengths")

    l0, l1 = _init_lists(leaf_weight, maxbits)

    # In the last list, 2 * numsymbols - 2 active chains need to be created.
    # Two are already created in the initialization. Each BoundaryPM run
    # creates one.
    num_boundary_pm_runs = 2 * numsymbols - 4
    last = maxbits - 1
    for _ in range(num_boundary_pm_runs - 1):
        _boundary_pm(l0, l1, leaf_weight, numsymbols, last)
    _boundary_pm_final(l0, l1, leaf_weight, numsymbols, last)

    _extract_bit_lengths(l1[last], leaf_count, bitlengths)
    return 0  # OK.

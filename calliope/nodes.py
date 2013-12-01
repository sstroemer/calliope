"""
Functions to deal with nodes and their configuration
"""

from __future__ import print_function
from __future__ import division

import pandas as pd


def _generate_node(node, items, techs):
    """
    Returns a dict for a given node. Dict keys for permitted technologies
    are the only ones that don't start with '_'.

    Args:
        node : (str) name of the node
        items : (AttrDict) node settings
        techs : (list) list of available technologies
    """
    # Mandatory basics
    d = {'_node': node, '_level': items.level, '_within': str(items.within)}
    # Override
    if 'override' in items:
        for k in items.override.keys_nested():
            d['_override.' + k] = items.override.get_key(k)
    # Permitted echnologies
    for y in techs:
        if y in items.techs:
            d[y] = 1
        else:
            d[y] = 0
    return d


def explode_node(k):
    """Expands the given key ``k``. ``k``s of the form ``'1--3'`` or
    ``'1,2,3'`` are both expanded into the list ``['1', '2', '3']``.

    Can deal with any combination, e.g. ``'1--3,6,9--11,a'`` results in::

        ['1', '2', '3', '6', '9', '10', '11', 'a']

    Always returns a list, even if ``k`` is just a simple key,
    i.e. ``explode_nodes('1')`` returns ``['1']``.

    """
    assert isinstance(k, str)  # Ensure sure we don't pass in other things
    finalkeys = []
    subkeys = k.split(',')
    for sk in subkeys:
        if '--' in sk:
            begin, end = sk.split('--')
            finalkeys += [str(i).strip()
                          for i in range(int(begin), int(end)+1)]
        else:
            finalkeys += [sk.strip()]
    if finalkeys == [] or finalkeys == ['']:
        raise KeyError('Empty key')
    return finalkeys


def get_nodes(d):
    """ Return a list of all nodes in the given dictionary, expanding
    nodes in compact representation (such as '1--10') as needed.

    """
    l = []
    for k in d.keys():
        k = explode_node(k)
        l.extend(k)
    return l


def generate_node_matrix(d, techs):
    """Generate a pandas DataFrame indexed by nodes, containing a column
    for each technology in `techs` and 1 if that node is allowed to
    use the technology, else 0.

    The DataFrame also contains _level and _within columns for grouping
    nodes into layers and zones.

    """
    rows = []
    for k, v in d.iteritems():
        if '--' in k or ',' in k:
            allnodes = explode_node(k)
            for n in allnodes:
                rows.append(_generate_node(n, v, techs))
        else:
            rows.append(_generate_node(k, v, techs))
    df = pd.DataFrame.from_records(rows)
    df.index = df._node
    df = df.drop(['_node'], axis=1)
    return df

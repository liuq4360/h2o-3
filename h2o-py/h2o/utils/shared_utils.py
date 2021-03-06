#!/usr/bin/env python
# -*- encoding: utf-8 -*-
#
# Copyright 2016 H2O.ai;  Apache License Version 2.0 (see LICENSE for details)
#
"""Shared utilities used by various classes, all placed here to avoid circular imports.

This file INTENTIONALLY has NO module dependencies!
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import imp
import itertools
import os
import re
import sys

from h2o.utils.compatibility import *  # NOQA
from h2o.utils.typechecks import assert_is_type, is_type, numeric

# private static methods
_id_ctr = 0


def _py_tmp_key(append):
    global _id_ctr
    _id_ctr += 1
    return "py_" + str(_id_ctr) + append


def temp_ctr():
    return _id_ctr


def can_use_pandas():
    try:
        imp.find_module('pandas')
        return True
    except ImportError:
        return False


def can_use_numpy():
    try:
        imp.find_module('numpy')
        return True
    except ImportError:
        return False


_url_safe_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
_url_chars_map = [chr(i) if chr(i) in _url_safe_chars else "%%%02X" % i for i in range(256)]

def url_encode(s):
    # Note: type cast str(s) will not be needed once all code is made compatible
    return "".join(_url_chars_map[c] for c in bytes_iterator(s))

def quote(s):
    return url_encode(s)


def urlopen():
    if PY3:
        from urllib import request
        return request.urlopen
    else:
        import urllib2
        return urllib2.urlopen

def clamp(x, xmin, xmax):
    """Return the value of x, clamped from below by `xmin` and from above by `xmax`."""
    return max(xmin, min(x, xmax))

def _gen_header(cols):
    return ["C" + str(c) for c in range(1, cols + 1, 1)]


def _check_lists_of_lists(python_obj):
    # check we have a lists of flat lists
    # returns longest length of sublist
    most_cols = 0
    for l in python_obj:
        # All items in the list must be a list!
        if not isinstance(l, (tuple, list)):
            raise ValueError("`python_obj` is a mixture of nested lists and other types.")
        most_cols = max(most_cols, len(l))
        for ll in l:
            # in fact, we must have a list of flat lists!
            if isinstance(ll, (tuple, list)):
                raise ValueError("`python_obj` is not a list of flat lists!")
    return most_cols


def _handle_python_lists(python_obj, check_header):
    # convert all inputs to lol
    if _is_list_of_lists(python_obj):  # do we have a list of lists: [[...], ..., [...]] ?
        ncols = _check_lists_of_lists(python_obj)  # must be a list of flat lists, raise ValueError if not
    elif isinstance(python_obj, (list, tuple)):  # single list
        ncols = 1
        python_obj = [[e] for e in python_obj]
    else:  # scalar
        python_obj = [[python_obj]]
        ncols = 1
    # create the header
    if check_header == 1:
        header = python_obj[0]
        python_obj = python_obj[1:]
    else:
        header = _gen_header(ncols)
    # shape up the data for csv.DictWriter
    # data_to_write = [dict(list(zip(header, row))) for row in python_obj]
    return header, python_obj


def stringify_list(arr):
    return "[%s]" % ",".join(stringify_list(item) if isinstance(item, list) else str(item)
                             for item in arr)


def _is_list(l):
    return isinstance(l, (tuple, list))


def _is_str_list(l):
    return is_type(l, [str])


def _is_num_list(l):
    return is_type(l, [numeric])


def _is_list_of_lists(o):
    return any(isinstance(l, (tuple, list)) for l in o)


def _handle_numpy_array(python_obj, header):
    return _handle_python_lists(python_obj.tolist(), header)


def _handle_pandas_data_frame(python_obj, header):
    data = _handle_python_lists(python_obj.as_matrix().tolist(), -1)[1]
    return list(python_obj.columns), data

def _handle_python_dicts(python_obj, check_header):
    header = list(python_obj.keys())
    is_valid = all(re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", col) for col in header)  # is this a valid header?
    if not is_valid:
        raise ValueError(
            "Did not get a valid set of column names! Must match the regular expression: ^[a-zA-Z_][a-zA-Z0-9_.]*$ ")
    for k in python_obj:  # check that each value entry is a flat list/tuple or single int, float, or string
        v = python_obj[k]
        if isinstance(v, (tuple, list)):  # if value is a tuple/list, then it must be flat
            if _is_list_of_lists(v):
                raise ValueError("Values in the dictionary must be flattened!")
        elif is_type(v, str, numeric):
            python_obj[k] = [v]
        else:
            raise ValueError("Encountered invalid dictionary value when constructing H2OFrame. Got: {0}".format(v))

    zipper = getattr(itertools, "zip_longest", None) or getattr(itertools, "izip_longest", None) or zip
    rows = list(map(list, zipper(*list(python_obj.values()))))
    data_to_write = [dict(list(zip(header, row))) for row in rows]
    return header, data_to_write


def _is_fr(o):
    return o.__class__.__name__ == "H2OFrame"  # hack to avoid circular imports


def _quoted(key):
    if key is None: return "\"\""
    # mimic behavior in R to replace "%" and "&" characters, which break the call to /Parse, with "."
    # key = key.replace("%", ".")
    # key = key.replace("&", ".")
    is_quoted = len(re.findall(r'\"(.+?)\"', key)) != 0
    key = key if is_quoted else '"' + key + '"'
    return key


def _locate(path):
    """Search for a relative path and turn it into an absolute path.
    This is handy when hunting for data files to be passed into h2o and used by import file.
    Note: This function is for unit testing purposes only.

    Parameters
    ----------
    path : str
      Path to search for

    :return: Absolute path if it is found.  None otherwise.
    """

    tmp_dir = os.path.realpath(os.getcwd())
    possible_result = os.path.join(tmp_dir, path)
    while True:
        if os.path.exists(possible_result):
            return possible_result

        next_tmp_dir = os.path.dirname(tmp_dir)
        if next_tmp_dir == tmp_dir:
            raise ValueError("File not found: " + path)

        tmp_dir = next_tmp_dir
        possible_result = os.path.join(tmp_dir, path)


def get_human_readable_bytes(size):
    """
    Convert given number of bytes into a human readable representation, i.e. add prefix such as kb, Mb, Gb,
    etc. The `size` argument must be a non-negative integer.

    :param size: integer representing byte size of something
    :return: string representation of the size, in human-readable form
    """
    if size == 0: return "0"
    if size is None: return ""
    assert_is_type(size, int)
    assert size >= 0, "`size` cannot be negative, got %d" % size
    suffixes = "PTGMk"
    maxl = len(suffixes)
    for i in range(maxl + 1):
        shift = (maxl - i) * 10
        if size >> shift == 0: continue
        ndigits = 0
        for nd in [3, 2, 1]:
            if size >> (shift + 12 - nd * 3) == 0:
                ndigits = nd
                break
        if ndigits == 0 or size == (size >> shift) << shift:
            rounded_val = str(size >> shift)
        else:
            rounded_val = "%.*f" % (ndigits, size / (1 << shift))
        return "%s %sb" % (rounded_val, suffixes[i] if i < maxl else "")


def get_human_readable_time(time_ms):
    """
    Convert given duration in milliseconds into a human-readable representation, i.e. hours, minutes, seconds,
    etc. More specifically, the returned string may look like following:
        1 day 3 hours 12 mins
        3 days 0 hours 0 mins
        8 hours 12 mins
        34 mins 02 secs
        13 secs
        541 ms
    In particular, the following rules are applied:
        * milliseconds are printed only if the duration is less than a second;
        * seconds are printed only if the duration is less than an hour;
        * for durations greater than 1 hour we print days, hours and minutes keeping zeros in the middle (i.e. we
          return "4 days 0 hours 12 mins" instead of "4 days 12 mins").

    :param time_ms: duration, as a number of elapsed milliseconds.
    :return: human-readable string representation of the provided duration.
    """
    millis = time_ms % 1000
    secs = (time_ms // 1000) % 60
    mins = (time_ms // 60000) % 60
    hours = (time_ms // 3600000) % 24
    days = (time_ms // 86400000)

    res = ""
    if days > 1:
        res += "%d days" % days
    elif days == 1:
        res += "1 day"

    if hours > 1 or (hours == 0 and res):
        res += " %d hours" % hours
    elif hours == 1:
        res += " 1 hour"

    if mins > 1 or (mins == 0 and res):
        res += " %d mins" % mins
    elif mins == 1:
        res += " 1 min"

    if days == 0 and hours == 0:
        res += " %02d secs" % secs
    if not res:
        res = " %d ms" % millis

    return res.strip()


def print2(msg, flush=False, end="\n"):
    """
    This function exists here ONLY because Sphinx.ext.autodoc gets into a bad state when seeing the print()
    function. When in that state, autodoc doesn't display any errors or warnings, but instead completely
    ignores the "bysource" member-order option.
    """
    print(msg, end=end)
    if flush: sys.stdout.flush()


gen_header = _gen_header
py_tmp_key = _py_tmp_key
locate = _locate
quoted = _quoted
is_list = _is_list
is_fr = _is_fr
handle_python_dicts = _handle_python_dicts
handle_pandas_data_frame = _handle_pandas_data_frame
handle_numpy_array = _handle_numpy_array
is_list_of_lists = _is_list_of_lists
is_num_list = _is_num_list
is_str_list = _is_str_list
handle_python_lists = _handle_python_lists
check_lists_of_lists = _check_lists_of_lists


def deprecated(message):
    """The decorator to mark deprecated functions."""
    from traceback import extract_stack
    assert message, "`message` argument in @deprecated is required."

    def deprecated_decorator(fun):
        return fun

        def decorator_invisible(*args, **kwargs):
            stack = extract_stack()
            assert len(stack) >= 2 and stack[-1][2] == "decorator_invisible", "Got confusing stack... %r" % stack
            print("[WARNING] in %s line %d:" % (stack[-2][0], stack[-2][1]))
            print("    >>> %s" % (stack[-2][3] or "????"))
            print("        ^^^^ %s" % message)
            return fun(*args, **kwargs)

        decorator_invisible.__doc__ = message
        decorator_invisible.__name__ = fun.__name__
        decorator_invisible.__module__ = fun.__module__
        decorator_invisible.__deprecated__ = True
        return decorator_invisible

    return deprecated_decorator

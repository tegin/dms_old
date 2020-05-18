import os
import re
import io
import sys
import base64
import shutil
import urllib
import logging
import hashlib
import binascii
import tempfile
import mimetypes
import unicodedata

from odoo.tools import human_size
from odoo.tools.mimetypes import guess_mimetype

def check_name(name):
    tmp_dir = tempfile.mkdtemp()
    try:
        open(os.path.join(tmp_dir, name), 'a').close()
    except IOError:
        return False
    finally:
        shutil.rmtree(tmp_dir)
    return True

def compute_name(name, suffix, escape_suffix):
    if escape_suffix:
        name, extension = os.path.splitext(name)
        return "%s(%s)%s" % (name, suffix, extension)
    else:
        return "%s(%s)" % (name, suffix)

def unique_name(name, names, escape_suffix=False):
    if not name in names:
        return name
    else:
        suffix = 1
        name = compute_name(name, suffix, escape_suffix)
        while name in names:
            suffix += 1
            name = compute_name(name, suffix, escape_suffix)
        return name

def guess_extension(filename=None, mimetype=None, binary=None):
    extension = filename and os.path.splitext(filename)[1][1:].strip().lower()
    if not extension and mimetype:
        extension = mimetypes.guess_extension(mimetype)[1:].strip().lower()
    if not extension and binary:
        mimetype = guess_mimetype(binary, default="")
        extension = mimetypes.guess_extension(mimetype)[1:].strip().lower()
    return extension

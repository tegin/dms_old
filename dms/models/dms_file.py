<<<<<<< HEAD
# Copyright 2020 Antoni Romera
# Copyright 2017-2019 MuK IT GmbH
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import base64
import functools
import hashlib
import json
import logging
import mimetypes
import operator
from collections import defaultdict

from odoo import SUPERUSER_ID, _, api, fields, models, tools
from odoo.exceptions import AccessError, ValidationError
from odoo.osv import expression
from odoo.tools.mimetypes import guess_mimetype

from ..tools import file

_logger = logging.getLogger(__name__)


class File(models.Model):

    _name = "dms.file"
    _description = "File"

    _inherit = [
        "dms.security.mixin",
        "dms.mixins.thumbnail",
    ]

    _order = "name asc"

    # ----------------------------------------------------------
    # Database
    # ----------------------------------------------------------

    name = fields.Char(string="Filename", required=True, index=True)

    active = fields.Boolean(
        string="Archived",
        default=True,
        help="If a file is set to archived, it is not displayed, but still exists.",
    )

    directory_id = fields.Many2one(
        comodel_name="dms.directory",
        string="Directory",
        domain="[('permission_create', '=', True)]",
        context="{'dms_directory_show_path': True}",
        ondelete="restrict",
        auto_join=True,
        required=True,
        index=True,
    )

    storage_id = fields.Many2one(
        related="directory_id.storage_id",
        comodel_name="dms.storage",
        string="Storage",
        auto_join=True,
        readonly=True,
        store=True,
    )

    is_hidden = fields.Boolean(
        string="Storage is Hidden", related="storage_id.is_hidden", readonly=True
    )

    company_id = fields.Many2one(
        related="storage_id.company_id",
        comodel_name="res.company",
        string="Company",
        readonly=True,
        store=True,
        index=True,
    )

    path_names = fields.Char(
        compute="_compute_path", string="Path Names", readonly=True, store=False
    )

    path_json = fields.Text(
        compute="_compute_path", string="Path Json", readonly=True, store=False
    )

    color = fields.Integer(string="Color", default=0)

    category_id = fields.Many2one(
        comodel_name="dms.category",
        context="{'dms_category_show_path': True}",
        string="Category",
    )

    tag_ids = fields.Many2many(
        comodel_name="dms.tag",
        relation="dms_file_tag_rel",
        column1="fid",
        column2="tid",
        string="Tags",
    )

    content = fields.Binary(
        compute="_compute_content",
        inverse="_inverse_content",
        string="Content",
        attachment=False,
        prefetch=False,
        required=True,
        store=False,
    )

    extension = fields.Char(
        compute="_compute_extension", string="Extension", readonly=True, store=True
    )

    mimetype = fields.Char(
        compute="_compute_mimetype", string="Type", readonly=True, store=True
    )

    size = fields.Integer(string="Size", readonly=True)

    checksum = fields.Char(string="Checksum/SHA1", readonly=True, size=40, index=True)

    content_binary = fields.Binary(
        string="Content Binary", attachment=False, prefetch=False, invisible=True
    )

    save_type = fields.Char(
        compute="_compute_save_type",
        string="Current Save Type",
        invisible=True,
        prefetch=False,
    )

    migration = fields.Char(
        compute="_compute_migration",
        string="Migration Status",
        readonly=True,
        prefetch=False,
    )

    # ----------------------------------------------------------
    # Helper
    # ----------------------------------------------------------

    @api.model
    def _get_checksum(self, binary):
        return hashlib.sha1(binary or b"").hexdigest()

    @api.model
    def _get_content_inital_vals(self):
        return {"content_binary": False}

    @api.model
    def _update_content_vals(self, file, vals, binary):
        vals.update(
            {
                "checksum": self._get_checksum(binary),
                "size": binary and len(binary) or 0,
            }
        )
        return vals

    @api.model
    def _get_binary_max_size(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        return int(get_param("dms_web_utils.binary_max_size", default=25))

    @api.model
    def _get_forbidden_extensions(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        extensions = get_param("dms.forbidden_extensions", default="")
        return [extension.strip() for extension in extensions.split(",")]

    def _get_thumbnail_placeholder_name(self):
        return self.extension and "file_%s.svg" % self.extension or ""

    # ----------------------------------------------------------
    # Actions
    # ----------------------------------------------------------

    def action_migrate(self, logging=True):
        record_count = len(self)
        for index, dms_file in enumerate(self):
            if logging:
                info = (index + 1, record_count, dms_file.migration)
                _logger.info(_("Migrate File %s of %s [ %s ]") % info)
            dms_file.with_context(migration=True).write(
                {"content": dms_file.with_context({}).content}
            )

    def action_save_onboarding_file_step(self):
        self.env.user.company_id.set_onboarding_step_done(
            "documents_onboarding_file_state"
        )

    # ----------------------------------------------------------
    # SearchPanel
    # ----------------------------------------------------------

    @api.model
    def _search_panel_directory(self, **kwargs):
        search_domain = (kwargs.get("search_domain", []),)
        category_domain = kwargs.get("category_domain", [])
        if category_domain and len(category_domain):
            return "=", category_domain[0][2]
        if search_domain and len(search_domain):
            for domain in search_domain[0]:
                if domain[0] == "directory_id":
                    return domain[1], domain[2]
        return None, None

    @api.model
    def _search_panel_domain(self, field, operator, directory_id, comodel_domain=False):
        if not comodel_domain:
            comodel_domain = []
        files_ids = self.search([("directory_id", operator, directory_id)]).ids
        return expression.AND([comodel_domain, [(field, "in", files_ids)]])

    @api.model
    def search_panel_select_range(self, field_name, **kwargs):
        operator, directory_id = self._search_panel_directory(**kwargs)
        if directory_id and field_name == "directory_id":
            domain = [("parent_id", operator, directory_id)]
            values = self.env["dms.directory"].search_read(
                domain, ["display_name", "parent_id"]
            )
            return {
                "parent_field": "parent_id",
                "values": values if len(values) > 1 else [],
            }
        return super(File, self).search_panel_select_range(field_name, **kwargs)

    @api.model
    def search_panel_select_multi_range(self, field_name, **kwargs):
        operator, directory_id = self._search_panel_directory(**kwargs)
        if field_name == "tag_ids":
            sql_query = """
                SELECT t.name AS name, t.id AS id, c.name AS group_name,
                    c.id AS group_id, COUNT(r.fid) AS count
                FROM dms_tag t
                JOIN dms_category c ON t.category_id = c.id
                LEFT JOIN dms_file_tag_rel r ON t.id = r.tid
                {directory_where_clause}
                GROUP BY c.name, c.id, t.name, t.id
                ORDER BY c.name, c.id, t.name, t.id;
            """
            where_clause = ""
            if directory_id:
                directory_where_clause = "WHERE r.fid = ANY (VALUES {ids})"
                file_ids = self.search([("directory_id", operator, directory_id)]).ids
                where_clause = (
                    ""
                    if not file_ids
                    else directory_where_clause.format(
                        ids=", ".join(map(lambda id: "(%s)" % id, file_ids))
                    )
                )
            self.env.cr.execute(
                sql_query.format(directory_where_clause=where_clause), []
            )
            return self.env.cr.dictfetchall()
        if directory_id and field_name in ["directory_id", "category_id"]:
            comodel_domain = kwargs.pop("comodel_domain", [])
            directory_comodel_domain = self._search_panel_domain(
                "files", operator, directory_id, comodel_domain
            )
            return super(File, self).search_panel_select_multi_range(
                field_name, comodel_domain=directory_comodel_domain, **kwargs
            )
        return super(File, self).search_panel_select_multi_range(field_name, **kwargs)

    # ----------------------------------------------------------
    # Read
    # ----------------------------------------------------------

    @api.depends("name", "directory_id", "directory_id.parent_path")
    def _compute_path(self):
        records_with_directory = self - self.filtered(lambda rec: not rec.directory_id)
        if records_with_directory:
            paths = [
                list(map(int, rec.directory_id.parent_path.split("/")[:-1]))
                for rec in records_with_directory
            ]
            model = self.env["dms.directory"].with_context(
                dms_directory_show_path=False
            )
            directories = model.browse(set(functools.reduce(operator.concat, paths)))
            data = dict({d.id: d for d in directories._filter_access("read")})
            for record in self:
                path_names = []
                path_json = []
                for directory_id in reversed(
                    list(map(int, record.directory_id.parent_path.split("/")[:-1]))
                ):
                    if directory_id not in data:
                        break
                    path_names.append(data[directory_id].name)
                    path_json.append(
                        {
                            "model": model._name,
                            "name": data[directory_id].name,
                            "id": directory_id,
                        }
                    )

                path_names.reverse()
                path_json.reverse()
                name = record.name_get()
                path_names.append(name[0][1])
                path_json.append(
                    {
                        "model": record._name,
                        "name": name[0][1],
                        "id": isinstance(record.id, int) and record.id or 0,
                    }
                )
                record.update(
                    {
                        "path_names": "/".join(path_names),
                        "path_json": json.dumps(path_json),
                    }
                )

    @api.depends("name")
    def _compute_extension(self):
        for record in self:
            record.extension = file.guess_extension(record.name)

    @api.depends("name")
    def _compute_mimetype(self):
        for record in self:
            mimetype = record.name and mimetypes.guess_type(record.name)[0]
            if not mimetype:
                binary = base64.b64decode(record.with_context({}).content or "")
                mimetype = guess_mimetype(binary, default="application/octet-stream")
            record.mimetype = mimetype

    @api.depends("content_binary")
    def _compute_content(self):
        for record in self:
            record.content = record.content_binary

    @api.depends("content_binary")
    def _compute_save_type(self):
        for record in self:
            record.save_type = "database"

    @api.depends("storage_id", "storage_id.save_type")
    def _compute_migration(self):
        storage_model = self.env["dms.storage"]
        save_field = storage_model._fields["save_type"]
        values = save_field._description_selection(self.env)
        selection = {value[0]: value[1] for value in values}
        for record in self:
            storage_type = record.storage_id.save_type
            if storage_type != record.save_type:
                storage_label = selection.get(storage_type)
                file_label = selection.get(record.save_type)
                record.migration = "{} > {}".format(file_label, storage_label)
            else:
                record.migration = selection.get(storage_type)

    def read(self, fields=None, load="_classic_read"):
        self.check_directory_access("read", {}, True)
        return super(File, self).read(fields, load=load)

    # ----------------------------------------------------------
    # View
    # ----------------------------------------------------------

    @api.onchange("category_id")
    def _change_category(self):
        res = {"domain": {"tag_ids": [("category_id", "=", False)]}}
        if self.category_id:
            res.update(
                {
                    "domain": {
                        "tag_ids": [
                            "|",
                            ("category_id", "=", False),
                            ("category_id", "child_of", self.category_id.id),
                        ]
                    }
                }
            )
        tags = self.tag_ids.filtered(
            lambda rec: not rec.category_id or rec.category_id == self.category_id
        )
        self.tag_ids = tags
        return res

    # ----------------------------------------------------------
    # Security
    # ----------------------------------------------------------

    @api.model
    def _get_directories_from_database(self, file_ids):
        if not file_ids:
            return self.env["dms.directory"]
        return self.env["dms.file"].browse(file_ids).mapped("directory_id")

    @api.model
    def _read_group_process_groupby(self, gb, query):
        if self.env.user.id == SUPERUSER_ID:
            return super(File, self)._read_group_process_groupby(gb, query)
        directories = (
            self.env["dms.directory"].with_context(prefetch_fields=False).search([])
        )
        if directories:
            where_clause = '"{table}"."{field}" = ANY (VALUES {ids})'.format(
                table=self._table,
                field="directory_id",
                ids=", ".join(map(lambda id: "(%s)" % id, directories.ids)),
            )
            query.where_clause += [where_clause]
        else:
            query.where_clause += ["0=1"]
        return super(File, self)._read_group_process_groupby(gb, query)

    @api.model
    def _search(
        self,
        args,
        offset=0,
        limit=None,
        order=None,
        count=False,
        access_rights_uid=None,
    ):
        result = super(File, self)._search(
            args, offset, limit, order, False, access_rights_uid
        )
        if self.env.user.id == SUPERUSER_ID:
            return len(result) if count else result
        if not result:
            return 0 if count else []
        file_ids = set(result)
        directories = self._get_directories_from_database(result)
        for directory in directories - directories._filter_access("read"):
            file_ids -= set(directory.sudo().mapped("file_idgs").ids)
        return len(file_ids) if count else list(file_ids)

    def _filter_access(self, operation):
        records = super(File, self)._filter_access(operation)
        if self.env.user.id == SUPERUSER_ID:
            return records
        directories = self._get_directories_from_database(records.ids)
        for directory in directories - directories._filter_access("read"):
            records -= self.browse(directory.sudo().mapped("files").ids)
        return records

    def check_access(self, operation, raise_exception=False):
        res = super(File, self).check_access(operation, raise_exception)
        try:
            return res and self.check_directory_access(operation) is None
        except AccessError:
            if raise_exception:
                raise
            return False

    def check_directory_access(self, operation, vals=False, raise_exception=False):
        if not vals:
            vals = {}
        if self.env.user.id == SUPERUSER_ID:
            return None
        if "directory_id" in vals and vals["directory_id"]:
            records = self.env["dms.directory"].browse(vals["directory_id"])
        else:
            records = self._get_directories_from_database(self.ids)
        return records.check_access(operation, raise_exception)

    # ----------------------------------------------------------
    # Constrains
    # ----------------------------------------------------------

    @api.constrains("name")
    def _check_name(self):
        for record in self:
            if not file.check_name(record.name):
                raise ValidationError(_("The file name is invalid."))
            files = record.sudo().directory_id.file_ids.name_get()
            if list(
                filter(
                    lambda file: file[1] == record.name and file[0] != record.id, files
                )
            ):
                raise ValidationError(_("A file with the same name already exists."))

    @api.constrains("extension")
    def _check_extension(self):
        for record in self:
            if (
                record.extension
                and record.extension in self._get_forbidden_extensions()
            ):
                raise ValidationError(_("The file has a forbidden file extension."))

    @api.constrains("size")
    def _check_size(self):
        for record in self:
            if record.size and record.size > self._get_binary_max_size() * 1024 * 1024:
                raise ValidationError(
                    _("The maximum upload size is %s MB).")
                    % self._get_binary_max_size()
                )

    @api.constrains("directory_id")
    def _check_directory_access(self):
        for record in self:
            if not record.directory_id.check_access("create", raise_exception=False):
                raise ValidationError(
                    _("The directory has to have the permission to create files.")
                )

    # ----------------------------------------------------------
    # Create, Update, Delete
    # ----------------------------------------------------------

    def _inverse_content(self):
        updates = defaultdict(set)
        for record in self:
            values = self._get_content_inital_vals()
            binary = base64.b64decode(record.content or "")
            values = self._update_content_vals(record, values, binary)
            values.update({"content_binary": record.content})
            updates[tools.frozendict(values)].add(record.id)
        with self.env.norecompute():
            for vals, ids in updates.items():
                self.browse(ids).write(dict(vals))
        self.recompute()

    @api.returns("self", lambda value: value.id)
    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or [])
        names = []
        if "directory_id" in default:
            model = self.env["dms.directory"]
            directory = model.browse(default["directory_id"])
            names = directory.sudo().file_ids.mapped("name")
        else:
            names = self.sudo().directory_id.file_ids.mapped("name")
        default.update({"name": file.unique_name(self.name, names, self.extension)})
        self.check_directory_access("create", default, True)
        return super(File, self).copy(default)

    def write(self, vals):
        self.check_directory_access("write", vals, True)
        self.check_lock()
        return super(File, self).write(vals)

    def unlink(self):
        self.check_directory_access("unlink", {}, True)
        self.check_lock()
        return super(File, self).unlink()

    # ----------------------------------------------------------
    # Locking fields and functions
    # ----------------------------------------------------------

    locked_by = fields.Many2one(comodel_name="res.users", string="Locked by")

    is_locked = fields.Boolean(compute="_compute_locked", string="Locked")

    is_lock_editor = fields.Boolean(compute="_compute_locked", string="Editor")

    # ----------------------------------------------------------
    # Locking
    # ----------------------------------------------------------

    def lock(self):
        self.write({"locked_by": self.env.uid})

    def unlock(self):
        self.write({"locked_by": None})

    @api.model
    def _check_lock_editor(self, lock_uid):
        return lock_uid in (self.env.uid, SUPERUSER_ID)

    def check_lock(self):
        for record in self:
            if record.locked_by.exists() and not self._check_lock_editor(
                record.locked_by.id
            ):
                message = _("The record (%s [%s]) is locked, by an other user.")
                raise AccessError(message % (record._description, record.id))

    # ----------------------------------------------------------
    # Read, View
    # ----------------------------------------------------------

    @api.depends("locked_by")
    def _compute_locked(self):
        for record in self:
            if record.locked_by.exists():
                record.update(
                    {
                        "is_locked": True,
                        "is_lock_editor": record.locked_by.id == record.env.uid,
                    }
                )
            else:
                record.update({"is_locked": False, "is_lock_editor": False})
=======
# -*- coding: utf-8 -*-

###################################################################################
# 
#    Copyright (C) 2017 MuK IT GmbH
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
###################################################################################

import os
import re
import json
import base64
import logging
import mimetypes

from odoo import _
from odoo import models, api, fields
from odoo.tools import ustr
from odoo.tools.mimetypes import guess_mimetype
from odoo.exceptions import ValidationError, AccessError

from odoo.addons.muk_dms.models import dms_base

_logger = logging.getLogger(__name__)

_img_path = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static/src/img'))

class File(dms_base.DMSModel):
    _name = 'muk_dms.file'
    _description = "File"
    
    _inherit = 'muk_dms.access'
    
    #----------------------------------------------------------
    # Database
    #----------------------------------------------------------
    
    name = fields.Char(
        string="Filename", 
        required=True)
    
    settings = fields.Many2one(
        'muk_dms.settings', 
        string="Settings",
        store=True,
        auto_join=True,
        ondelete='restrict', 
        compute='_compute_settings')
    
    content = fields.Binary(
        string='Content', 
        required=True,
        compute='_compute_content',
        inverse='_inverse_content')
    
    reference = fields.Reference(
        selection=[('muk_dms.data', _('Data'))],
        string="Data Reference", 
        readonly=True)
    
    directory = fields.Many2one(
        'muk_dms.directory', 
        string="Directory",
        ondelete='restrict',  
        auto_join=True,
        required=True)
    
    extension = fields.Char(
        string='Extension',
        compute='_compute_extension',
        readonly=True,
        store=True)
    
    mimetype = fields.Char(
        string='Type',
        compute='_compute_mimetype',
        readonly=True,
        store=True)
    
    size = fields.Integer(
        string='Size', 
        readonly=True)
    
    custom_thumbnail = fields.Binary(
        string="Custom Thumbnail")
    
    thumbnail = fields.Binary(
        compute='_compute_thumbnail',
        string="Thumbnail")
    
    path = fields.Char(
        string="Path",
        store=True,
        readonly=True,
        compute='_compute_path')
    
    relational_path = fields.Text(
        string="Path",
        store=True,
        readonly=True,
        compute='_compute_relational_path')
    
    index_content = fields.Text(
        string='Indexed Content',
        compute='_compute_index',
        readonly=True,
        store=True,
        prefetch=False)
    
    locked_by = fields.Reference(
        string='Locked by',
        related='locked.locked_by_ref')
    
    #----------------------------------------------------------
    # Functions
    #----------------------------------------------------------
    
    def notify_change(self, values, refresh=False, operation=None):
        super(File, self).notify_change(values, refresh, operation)
        if "index_files" in values:
            self._compute_index()
        if "save_type" in values:
            self._update_reference_type()
            
    
    def trigger_computation_up(self, fields):
        self.directory.trigger_computation(fields)
        
    def trigger_computation(self, fields, refresh=True, operation=None):
        super(File, self).trigger_computation(fields, refresh, operation)
        values = {}
        if "settings" in fields:
            values.update(self.with_context(operation=operation)._compute_settings(write=False)) 
        if "path" in fields:
            values.update(self.with_context(operation=operation)._compute_path(write=False)) 
            values.update(self.with_context(operation=operation)._compute_relational_path(write=False)) 
        if "extension" in fields:
            values.update(self.with_context(operation=operation)._compute_extension(write=False)) 
        if "mimetype" in fields:
            values.update(self.with_context(operation=operation)._compute_mimetype(write=False)) 
        if "index_content" in fields:
            values.update(self.with_context(operation=operation)._compute_index(write=False)) 
        if values:
            self.write(values);     
            if "settings" in fields:
                self.notify_change({'save_type': self.settings.save_type})
            
    #----------------------------------------------------------
    # Read, View 
    #----------------------------------------------------------
        
    def _compute_settings(self, write=True):
        if write:
            for record in self:
                record.settings = record.directory.settings   
        else:
            self.ensure_one()
            return {'settings': self.directory.settings.id}         
                 
    def _compute_extension(self, write=True):
        if write:
            for record in self:
                record.extension = os.path.splitext(record.name)[1]
        else:
            self.ensure_one()
            return {'extension': os.path.splitext(self.name)[1]}
                          
    def _compute_mimetype(self, write=True):
        def get_mimetype(record):
            mimetype = mimetypes.guess_type(record.name)[0]
            if (not mimetype or mimetype == 'application/octet-stream') and record.content:
                mimetype = guess_mimetype(base64.b64decode(record.content))
            return mimetype or 'application/octet-stream'
        if write:
            for record in self:
                record.mimetype = get_mimetype(record)
        else:
            self.ensure_one()
            return {'mimetype': get_mimetype(self)}   
                    
    def _compute_path(self, write=True):
        if write:
            for record in self:
                record.path = "%s%s" % (record.directory.path, record.name)   
        else:
            self.ensure_one()
            return {'path': "%s%s" % (self.directory.path, self.name)}   
            
    def _compute_relational_path(self, write=True):
        def get_relational_path(record):
            path = json.loads(record.directory.relational_path)
            path.append({
                'model': record._name,
                'id': record.id,
                'name': record.name})
            return json.dumps(path)  
        if write:
            for record in self:
                record.relational_path = get_relational_path(record)
        else:
            self.ensure_one()
            return {'relational_path': get_relational_path(self)}   
    
    def _compute_index(self, write=True):
        def get_index(record):
            type = record.mimetype.split('/')[0] if record.mimetype else record._compute_mimetype(write=False)['mimetype']  
            index_files = record.settings.index_files if record.settings else record.directory.settings.index_files
            if type and type.split('/')[0] == 'text' and record.content and index_files:
                words = re.findall(b"[\x20-\x7E]{4,}", base64.b64decode(record.content) if record.content else b'')
                return b"\n".join(words).decode('ascii')
            else:
                return None   
        if write:
            for record in self:
                record.index_content = get_index(record)
        else:
            self.ensure_one()
            return {'index_content': get_index(self)}   
                    
    def _compute_content(self):
        for record in self:
            record.content = record._get_content()
            
    @api.depends('custom_thumbnail')
    def _compute_thumbnail(self):
        for record in self:
            if record.custom_thumbnail:
                record.thumbnail = record.with_context({}).custom_thumbnail        
            else:
                extension = record.extension and record.extension.strip(".") or ""
                path = os.path.join(_img_path, "file_%s.png" % extension)
                if not os.path.isfile(path):
                    path = os.path.join(_img_path, "file_unkown.png")
                with open(path, "rb") as image_file:
                    record.thumbnail = base64.b64encode(image_file.read())
            
    #----------------------------------------------------------
    # Create, Update, Delete
    #----------------------------------------------------------
    
    @api.constrains('name')
    def _check_name(self):
        if not self.check_name(self.name):
            raise ValidationError("The file name is invalid.")
        childs = self.directory.files.mapped(lambda rec: [rec.id, rec.name])
        duplicates = [rec for rec in childs if rec[1] == self.name and rec[0] != self.id]
        if duplicates:
            raise ValidationError(_("A file with the same name already exists."))
        
    @api.constrains('name')
    def _check_extension(self):
        config_parameter = self.env['ir.config_parameter']
        forbidden_extensions = config_parameter.sudo().get_param('muk_dms.forbidden_extensions', default="")
        forbidden_extensions = [x.strip() for x in forbidden_extensions.split(',')]
        file_extension = self._compute_extension(write=False)['extension']
        if file_extension and file_extension in forbidden_extensions:
            raise ValidationError(_("The file has a forbidden file extension."))
        
    @api.constrains('content')
    def _check_size(self):
        config_parameter = self.env['ir.config_parameter']
        max_upload_size = config_parameter.sudo().get_param('muk_dms.max_upload_size', default=25)
        try:
            max_upload_size = int(max_upload_size)
        except ValueError:
            max_upload_size = 25
        if max_upload_size * 1024 * 1024 < len(base64.b64decode(self.content)):
            raise ValidationError(_("The maximum upload size is %s MB).") % max_upload_size)
    
    def _after_create(self, vals):
        record = super(File, self)._after_create(vals)
        record._check_recomputation(vals)
        return record
        
    def _after_write_record(self, vals, operation):
        vals = super(File, self)._after_write_record(vals, operation)
        self._check_recomputation(vals, operation)
        return vals
    
    def _check_recomputation(self, values, operation=None):
        fields = []
        if 'name' in values:
            fields.extend(['extension', 'mimetype', 'path'])
        if 'directory' in values:
            fields.extend(['settings', 'path'])
        if 'content' in values:
            fields.extend(['index_content'])
        if fields:
            self.trigger_computation(fields)
        self._check_reference_values(values)
        if 'size' in values:
            self.trigger_computation_up(['size'])
                
    def _inverse_content(self):
        for record in self:
            if record.content:
                content = record.content
                directory = record.directory
                settings = record.settings if record.settings else directory.settings
                reference = record.reference
                if reference:
                    record._update_reference_content(content)
                else:
                    reference = record._create_reference(
                        settings, directory.path, record.name, content)
                record.reference = "%s,%s" % (reference._name, reference.id)
                record.size = len(base64.b64decode(content))
            else:
                record._unlink_reference()
                record.reference = None
    
    @api.returns('self', lambda value: value.id)
    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or [])
        names = self.directory.files.mapped('name')
        default.update({'name': self.unique_name(self.name, names, self.extension)})
        vals = self.copy_data(default)[0]
        if 'reference' in vals:
            del vals['reference']
        if not 'content' in vals:
            vals.update({'content': self.content})
        new = self.with_context(lang=None).create(vals)
        self.copy_translations(new)
        return new
    
    def _before_unlink_record(self):
        super(File, self)._before_unlink_record()
        self._unlink_reference()
                        
    #----------------------------------------------------------
    # Reference
    #----------------------------------------------------------
    
    def _create_reference(self, settings, path, filename, content):
        self.ensure_one()
        self.check_access('create', raise_exception=True)
        if settings.save_type == 'database':
            return self.env['muk_dms.data_database'].sudo().create({'data': content})
        return None
    
    def _update_reference_content(self, content):
        self.ensure_one()     
        self.check_access('write', raise_exception=True)
        self.reference.sudo().update({'content': content})
    
    def _update_reference_type(self):
        self.ensure_one()     
        self.check_access('write', raise_exception=True)
        if self.reference and self.settings.save_type != self.reference.type():
            reference = self._create_reference(self.settings, self.directory.path, self.name, self.content)
            self._unlink_reference()
            self.reference = "%s,%s" % (reference._name, reference.id)
    
    def _check_reference_values(self, values):
        self.ensure_one()
        self.check_access('write', raise_exception=True)
        if 'content' in values:
            self._update_reference_content(values['content'])
        if 'settings' in values:
            self._update_reference_type()
    
    def _get_content(self):
        self.ensure_one()
        self.check_access('read', raise_exception=True)
        return self.reference.sudo().content() if self.reference else None
    
    def _unlink_reference(self):
        self.ensure_one()
        self.check_access('unlink', raise_exception=True)
        if self.reference:
            self.reference.sudo().delete()
            self.reference.sudo().unlink()>>>>>>> update

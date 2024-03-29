# Copyright 2017-2019 MuK IT GmbH
# Copyright 2020 RGB Consulting
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

from odoo import api, fields, models


class DmsAccessGroups(models.Model):
    _name = "dms.access_groups"
    _description = "Record Access Groups"

    _parent_store = True
    _parent_name = "parent_group"

    name = fields.Char(string="Group Name", required=True, translate=True)
    parent_path = fields.Char(string="Parent Path", index=True)
    perm_read = fields.Boolean(string="Read Access")
    perm_create = fields.Boolean(string="Create Access")
    perm_write = fields.Boolean(string="Write Access")
    perm_unlink = fields.Boolean(string="Unlink Access")
    directories = fields.Many2many(
        comodel_name="dms.directory",
        relation="dms_directory_groups_rel",
        string="Directories",
        column1="gid",
        column2="aid",
        readonly=True,
    )
    count_users = fields.Integer(compute="_compute_users", string="Users", store=True)
    count_directories = fields.Integer(
        compute="_compute_count_directories", string="Count Directories"
    )

    @api.depends("directories")
    def _compute_count_directories(self):
        for record in self:
            record.count_directories = len(record.directories)

    @api.model
    def _add_magic_fields(self):
        super(DmsAccessGroups, self)._add_magic_fields()

        def add(name, field):
            if name not in self._fields:
                self._add_field(name, field)

        add(
            "parent_group",
            fields.Many2one(
                _module=self._module,
                comodel_name=self._name,
                string="Parent Group",
                ondelete="cascade",
                auto_join=True,
                index=True,
                automatic=True,
            ),
        )
        add(
            "child_groups",
            fields.One2many(
                _module=self._module,
                comodel_name=self._name,
                inverse_name="parent_group",
                string="Child Groups",
                automatic=True,
            ),
        )
        add(
            "groups",
            fields.Many2many(
                _module=self._module,
                comodel_name="res.groups",
                relation="%s_groups_rel" % (self._table),
                column1="gid",
                column2="rid",
                string="Groups",
                automatic=True,
            ),
        )
        add(
            "explicit_users",
            fields.Many2many(
                _module=self._module,
                comodel_name="res.users",
                relation="%s_explicit_users_rel" % (self._table),
                column1="gid",
                column2="uid",
                string="Explicit Users",
                automatic=True,
            ),
        )
        add(
            "users",
            fields.Many2many(
                _module=self._module,
                comodel_name="res.users",
                relation="%s_users_rel" % (self._table),
                column1="gid",
                column2="uid",
                string="Group Users",
                compute="_compute_users",
                store=True,
                automatic=True,
            ),
        )

    _sql_constraints = [
        ("name_uniq", "unique (name)", "The name of the group must be unique!")
    ]

    @api.model
    def default_get(self, fields_list):
        res = super(DmsAccessGroups, self).default_get(fields_list)
        if not self.env.context.get("groups_no_autojoin"):
            if "explicit_users" in res and res["explicit_users"]:
                res["explicit_users"] = res["explicit_users"] + [self.env.uid]
            else:
                res["explicit_users"] = [self.env.uid]
        return res

    @api.depends(
        "parent_group", "parent_group.users", "groups", "groups.users", "explicit_users"
    )
    def _compute_users(self):
        for record in self:
            users = record.mapped("groups.users")
            users |= record.mapped("explicit_users")
            users |= record.mapped("parent_group.users")
            record.update({"users": users, "count_users": len(users)})

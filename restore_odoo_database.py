#!/usr/bin/env python3
#
# Copyright (C) 2022 Mihran Thalhath (https://github.com/mihranthalhath)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#


"""
This script restores a database from an archived backup file.
Recommended to run this script as root.
"""

from datetime import datetime
import getpass
import os
import pathlib
import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import shutil
import subprocess
import uuid
import zipfile

# Change the parameters accordingly
odoo_directory = ""  # Odoo source code location. This is used to get the filestore path. If you are using a custom filestore directory,
                     # change the `filestore_destination` parameter accordingly.
filestore_destination = os.path.join(odoo_directory, ".local/share/Odoo/filestore", db_name)
backup_file = ""  # Path of the zip file to be restored
db_host = ""
db_port = ""
db_username = ""
db_password = ""
db_name = ""
# CAUTION: make sure that remote_working_directory is not an actual directory
# as we will be deleting the directory at the end of this script
remote_working_directory = "%s/tmp_db_restore_directory" % os.path.expanduser("~")
odoo_user = ""  # Odoo user that will be used to run the system

if (
    not filestore_destination
    or not backup_file
    or not db_host
    or not db_port
    or not db_username
    or not db_password
    or not db_name
):
    print("Please provide all the required parameters.")
    exit()

backup_file = pathlib.Path(backup_file)
if not backup_file.is_file():
    print("Backup file does not exist.")
    exit()

chosen_template = "template0"  # Odoo uses template0 by default
connection = psycopg2.connect(user=db_username, password=db_password, host=db_host, port=db_port, database="postgres")
connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cursor = connection.cursor()
cursor.execute("SELECT datname FROM pg_database WHERE datname = '%s'" % db_name)
if cursor.fetchall():
    print("Database %s already exists." % db_name)
    exit()

collate = sql.SQL("LC_COLLATE 'C'")
cursor.execute(
    sql.SQL("CREATE DATABASE {} ENCODING 'unicode' {} TEMPLATE {}").format(
        sql.Identifier(db_name), collate, sql.Identifier("template0")
    )
)

_default_parameters = {
    "database.secret": lambda: str(uuid.uuid4()),
    "database.uuid": lambda: str(uuid.uuid1()),
    "database.create_date": datetime.now(),
    "web.base.url": lambda: "http://localhost:8069",
    "base.login_cooldown_after": lambda: 10,
    "base.login_cooldown_duration": lambda: 60,
}

if zipfile.is_zipfile(backup_file):
    with zipfile.ZipFile(backup_file, "r") as zip_ref:
        filestore = [m for m in zip_ref.namelist() if m.startswith("filestore/")]
        zip_ref.extractall(remote_working_directory, ["dump.sql"] + filestore)
        if filestore:
            filestore_path = os.path.join(remote_working_directory, "filestore")
    pg_args = ["-q", "-f", os.path.join(remote_working_directory, "dump.sql")]
    args = []
    args.append("--dbname=" + db_name)
    pg_args = ("/usr/bin/psql",) + tuple(args + pg_args)
    with open(os.devnull) as dn:
        os.putenv("PGHOST", db_host)
        os.putenv("PGPORT", db_port)
        os.putenv("PGUSER", db_username)
        os.putenv("PGPASSWORD", db_password)
        print("Restoring database dump.")
        rc = subprocess.call(pg_args, stdout=dn, stderr=subprocess.STDOUT)
        if rc:
            print("Postgres subprocess {} error {}".format(pg_args, rc))
            print("Couldn't restore database dump")
            exit()
    connection = psycopg2.connect(
        user=db_username, password=db_password, host=db_host, port=db_port, database=db_name
    )
    cursor = connection.cursor()
    print("Configuring default database parameters")
    for key, func in _default_parameters.items():
        if type(func) != datetime:
            func = func()
        cursor.execute(sql.SQL("SELECT COUNT(*) FROM ir_config_parameter WHERE key = %s"), (key,))
        if not cursor.fetchone()[0]:
            cursor.execute(sql.SQL("INSERT INTO ir_config_parameter (key, value) VALUES (%s, %s)"), (key, func()))
        else:
            cursor.execute(sql.SQL("UPDATE ir_config_parameter SET value = %s WHERE key = %s"), (func, key))
    if filestore_path:
        shutil.move(filestore_path, filestore_destination)
        print("Moved filestore to %s" % filestore_destination)

        # Change the ownership of the filestore directory to odoo user
        if odoo_user:
            os.system("chown -R {}:{} {}".format(odoo_user, odoo_user, filestore_destination))

        shutil.rmtree(remote_working_directory, ignore_errors=True, onerror=None)

        print("Restored database %s" % db_name)
else:
    print("The backup file must be in zip format.")
    exit()


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
This script takes an archived backup of a particular database including filestore.
Script can be used to run as a cronjob to take regular backups.
Recommended to run this script as root.
"""

import json
import os
import pathlib
import psycopg2
import shutil
import subprocess
import time

# Change the parameters accordingly
odoo_directory = ""  # Odoo source code location. This is used to get the filestore path. If you are using a custom filestore directory,
                     # change the `filestore_directory` parameter accordingly.
db_name = ""
filestore_directory = os.path.join(odoo_directory, ".local/share/Odoo/filestore", db_name)
backup_directory = ""  # Path to store backup file
db_host = ""
db_port = ""
db_username = ""
db_password = ""
owner_user = ""  # The user who should be the owner of the backup file
odoo_version = ""  # (Eg.: 13.0, 14.0, 15.0)
delete_old_files = False  # Value can either be False or True. CAUTION: This deletes all zip files older than `number_of_days`.


if (
    not filestore_directory
    or not backup_directory
    or not db_host
    or not db_port
    or not db_username
    or not db_password
    or not db_name
    or not odoo_version
):
    print("Please provide all the required parameters.")
    exit()

os.makedirs(backup_directory, exist_ok=True)
logfile = os.path.join(backup_directory, "logfile.txt")
file = open(logfile, "w")
file.close()


def log(string):
    file = open(logfile, "a")
    file.write(time.strftime("%Y-%m-%d-%H-%M-%S", time.gmtime()) + ": " + str(string) + "\n")
    file.close()
    print(string)


# Delete files older than `number_of_days`
# Currently set to 7 days ago from when this script starts to run.
if delete_old_files:
    number_of_days = 7
    x_days_ago = time.time() - (60 * 60 * 24 * number_of_days)


try:
    dumper = " --host %s --port %s --username %s --file=%s %s"
    os.putenv("PGPASSWORD", db_password)
    log("%s database backup has started." % db_name)

    zip_file_name = "{}_{}".format(db_name, str(time.strftime("%Y-%m-%d_%H-%M-%S")))
    db_directory = os.path.join(backup_directory, zip_file_name)
    os.makedirs(db_directory, exist_ok=True)
    file_path = os.path.join(db_directory, "dump.sql")
    backup_command = "pg_dump" + dumper % (db_host, db_port, db_username, file_path, db_name)
    subprocess.call(backup_command, shell=True)
    log("%s database dump finished." % (db_name))

    # Let's create a connection to the db inorder to fetch the installed modules list
    log("Establising connection to database %s inorder to fetch the installed module list." % (db_name))
    connection = psycopg2.connect(user=db_username, password=db_password, host=db_host, port=db_port, database=db_name)
    cursor = connection.cursor()
    pg_version = "%d.%d" % divmod(cursor.connection.server_version / 100, 100)
    db_modules_query = "SELECT name, latest_version FROM ir_module_module WHERE state = 'installed'"
    cursor.execute(db_modules_query)
    modules = dict(cursor.fetchall())
    manifest = {
        "odoo_dump": "1",
        "db_name": db_name,
        "version": odoo_version,
        "version_info": [int(odoo_version.split(".")[0]), 0, 0, "final", 0, ""],
        "major_version": odoo_version,
        "pg_version": str(pg_version),
        "modules": modules,
    }
    with open(os.path.join(db_directory, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=4)

    # Copy filestore to our working directory
    filestore_working_directory = os.path.join(db_directory, "filestore")
    log("Copying filestore of %s database." % (db_name))
    shutil.copytree(filestore_directory, filestore_working_directory)

    # Archive the working directory in zip format
    zip_path = os.path.join(backup_directory, zip_file_name)
    log("Zipping up dump and filestore of %s database." % (db_name))
    shutil.make_archive(zip_path, "zip", db_directory)

    # Change the ownership of the backup file to the owner_user
    if owner_user:
        log("Changing ownership of backup file to %s." % (owner_user))
        os.system("chown -R {}:{} {}".format(owner_user, owner_user, backup_directory))

    # Remove the working directory
    shutil.rmtree(db_directory, ignore_errors=True, onerror=None)

    if delete_old_files:
        existing_zip_list = list(pathlib.Path(backup_directory).glob("*.zip"))
        flag = False
        for file in existing_zip_list:
            file_info = os.stat(file)
            if file_info.st_mtime < x_days_ago:
                log("Delete: %s" % (file))
                os.remove(file)
                flag = True
            else:
                log("Keeping: %s" % file)
        if flag:
            log("Backup files older than %s deleted." % time.strftime("%c", time.gmtime(x_days_ago)))

except Exception as error:
    log("Couldn't backup database - {} with exception {}.".format(db_name, error))

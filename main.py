import collections
import re
import socket
from ftplib import FTP, error_perm
import os
import zipfile

from dotenv import load_dotenv
from tqdm import tqdm
import inspect
import os

load_dotenv()

class Bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


process_map = {
    "main": "Main Application Flow",
    "create_zip_archive": "Archive Creation Process",
    "clear_ftp_directory": "FTP Directory Cleanup",
    "upload_folder_to_ftp": "FTP Upload Process",
    "delete_contents": "FTP Directory Cleanup (Recursive)",
    "check_ftp_login": "FTP Auth and Permissions Check",
    "safety_check": "Project Path Check"
}
def log_process(action, status="STARTED", details="", caller=None):
    """Log a process action with automatic caller mapping."""
    if not caller:
        caller = inspect.stack()[1].function  # Get the calling function name
    process_name = process_map.get(caller, "Unknown Process")  # Map to a custom process name
    color=""
    if status in ["STARTED", "FINISHED"]:
        color=Bcolors.OKCYAN + Bcolors.UNDERLINE
    if status in ["ONGOING"]:
        color=Bcolors.OKBLUE
    if status == 'STARTED':
        color = "\n"+color
    print(f"{color}PROCESS {status}:{Bcolors.ENDC}\t{Bcolors.FAIL} [{process_name}]{Bcolors.WARNING} {action}{Bcolors.ENDC} {"" if details == "" else f"({details})"}")


def normalize_path(path):
    """Normalize Windows path and ensure no trailing backslash."""
    return os.path.normpath(path)


def connect_ftp(server, username, password):
    """Connect to an FTP server and return the connection object."""
    caller = inspect.stack()[1].function
    ftp = FTP(server)
    ftp.login(user=username, passwd=password)
    log_process(action=f"{Bcolors.OKGREEN}Connected to FTP server: {server}", status="ONGOING", caller=caller)
    return ftp

def upload_file_with_progress(ftp, file_path, remote_file_name):
    """Upload a file to the FTP server with a progress bar."""
    file_size = os.path.getsize(file_path)
    desc_width = 50
    desc = f"{Bcolors.OKBLUE}PROCESS ONGOING:\t {Bcolors.FAIL}[FTP Upload Process] {Bcolors.ENDC}Uploading {remote_file_name[:desc_width]:<{desc_width}}"
    progress = tqdm(total=file_size, unit='B', unit_scale=True, desc=desc)

    def callback(data):
        progress.update(len(data))

    with open(file_path, 'rb') as f:
        ftp.storbinary(f"STOR {remote_file_name}", f, callback=callback)
    progress.close()

def clear_ftp_directory(server, username, password, remote_path, verbose=False):
    """
    Remove all files and subdirectories inside a specified FTP directory,
    but keep the directory itself.
    """
    log_process(action=f"Delete remote directory contents of {remote_path}", status="STARTED")
    def delete_contents(path):
        deleted = collections.Counter(files=0, folders=0)
        items = ftp.nlst(path)
        caller = inspect.stack()[1].function
        log_process(action=f"Total of {len(items)} items to delete in ({path}) directory", status="ONGOING",
                    caller=caller)
        for item in items:
            item_path = item
            try:
                ftp.cwd(item_path)
                deleted += delete_contents(item_path)
                ftp.cwd("..")
                ftp.rmd(item_path)
                deleted['folders'] += 1
                if verbose:
                    log_process(action=f"Deleted directory: {item_path}", status="ONGOING", caller=caller)
            except error_perm:
                ftp.delete(item_path)
                deleted['files'] += 1
                if verbose:
                    log_process(action=f"Deleted file: {item_path}", status="ONGOING", caller=caller)
        return deleted

    try:
        if input(f"{Bcolors.OKBLUE}PROCESS ONGOING:\t {Bcolors.FAIL}[FTP Directory Cleanup] {Bcolors.WARNING}Delete all contents of ({remote_path})?\n{Bcolors.OKBLUE}PROCESS ONGOING:\t {Bcolors.FAIL}[FTP Directory Cleanup] {Bcolors.ENDC}Press enter to proceed, type anything else to abort. ") != "":
            log_process(action=f"Delete remote directory contents of {remote_path}", status="FINISHED", details=f"Deleted total of {0} files and {0} folders")
            return

        ftp = connect_ftp(server, username, password)

        deleted_dict = delete_contents(remote_path)
        log_process(action=f"Delete remote directory contents of {remote_path}", status="FINISHED", details=f"Deleted total of {deleted_dict['files']} files and {deleted_dict['folders']} folders")
        ftp.quit()

    except Exception as e:
        print(f"An error occurred while clearing directory: {e}")

def upload_folder_to_ftp(server, username, password, folder_path, remote_path):
    """Upload a folder to an FTP server."""
    try:
        log_process(action=f"Upload local directory", status="STARTED", details=f"({folder_path}) -> ({remote_path})")
        folder_path = normalize_path(folder_path)
        ftp = connect_ftp(server, username, password)

        try:
            ftp.cwd(remote_path)
        except error_perm:
            print(f"Remote directory {remote_path} does not exist. Creating it.")
            ftp.mkd(remote_path)
            ftp.cwd(remote_path)

        for root, dirs, files in os.walk(folder_path):
            # Exclude .git and .gitignore
            dirs[:] = [d for d in dirs if d != '.git']
            files = [f for f in files if f != '.gitignore']

            relative_path = os.path.relpath(root, folder_path)
            current_remote_path = os.path.join(remote_path, relative_path).replace("\\", "/")
            try:
                ftp.cwd(current_remote_path)
            except error_perm:
                log_process(action="Creating directory on remote server", status="ONGOING", details=current_remote_path)
                ftp.mkd(current_remote_path)
                ftp.cwd(current_remote_path)

            # Upload files
            for file in files:
                local_file_path = os.path.join(root, file)
                upload_file_with_progress(ftp, local_file_path, file)

        ftp.quit()
        log_process(action=f"Upload local directory", status="FINISHED", details=f"({folder_path}) -> ({remote_path})")

    except Exception as e:
        print(f"An error occurred: {e}")

def create_zip_archive(source,verbose:bool=False):
    """Create a zip archive of a folder, excluding .git directory."""
    source = normalize_path(source)
    output_filename = os.path.basename(source)
    archive_path = os.path.join(source, f"{output_filename}.zip")
    log_process(action=f"Recreate project archive at", status="STARTED", details=source)
    try:
        if os.path.exists(archive_path):
            os.remove(archive_path)
            log_process(action=f"Deleted old archive at",status="ONGOING", details=archive_path)

        with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            count = 0
            for root, dirs, files in os.walk(source):

                dirs[:] = [d for d in dirs if d != '.git']
                files = [f for f in files if f != '.gitignore']
                for file in files:
                    file_path = os.path.join(root, file)
                    archive_name = os.path.relpath(file_path, source)
                    zipf.write(file_path, archive_name)
                    count+=1
                    if verbose:
                        # print(f"Added to archive: {archive_name}")
                        log_process(action=f"Added file to archive", status="ONGOING", details=archive_name)
        log_process(action=f"Created new project archive at", status="FINISHED", details=source)
        return archive_path

    except Exception as e:
        print(f"Error creating archive: {e}")
        return None

def safety_check(basename):
    """Check if the basename matches the required pattern 'tarX' where X is a digit."""
    log_process(f"Validating project folder name: {basename}", status="STARTED")
    pattern = r'^tar\d$'
    if not re.match(pattern, os.path.basename(basename)):
        log_process(action=f"Validation failed for folder name: {basename}", status="FINISHED", details="Invalid folder name")
        raise Exception("Project folder must be 'tarX' where X is the current exercise number you need to hand over.")
    log_process(action=f"Validation passed for folder name: {basename}", status="FINISHED")

def check_ftp_login(server, username, password, directory):
    """Check if FTP connection and directory access are successful."""
    try:
        log_process(action=f"Connecting to FTP server: {server}", status="STARTED")
        ftp = FTP(server)
        ftp.login(user=username, passwd=password)
        log_process(action=f"Login successful for FTP server: {server}", status="ONGOING")
        log_process(action=f"Attempting to access directory: {directory}", status="ONGOING")
        ftp.cwd(directory)
        log_process(action=f"Successfully accessed directory: {directory}", status="FINISHED")
        ftp.quit()
        return True
    except error_perm as e:
        log_process(action=f"Permission error: {e}", status="FINISHED", details="Permission denied")
        raise PermissionError(f"Permission error: {e}")
    except socket.gaierror as e:
        log_process(action=f"FTP connection error: {e}, please check the FTP IP address and try again", status="FINISHED", details="")
        raise ConnectionError(f"FTP connection error: {e}, please check the FTP IP address and try again")
    except Exception as e:
        log_process(action=f"An error occurred: ({e}), please screenshot the error + code and send to developer.", status="FINISHED", details="Unknown error")
        raise Exception(f"An error occurred: {e}, please screenshot the error + code and send to developer.")


def main():
    """
    README:
    This script is for LAZY people.
    It takes a project directory (named source) and does a couple of things automatically:

    1. Deletes all contents of remote ftp server's (ftp) 'tar' directory from past uploads
    2. Creates a '.zip' archive of your local project directory (deletes and creates if exists)
    3. Upload project folder to ftp server (excluding '.git' and '.gitignore' files incase you have a repo there)

    For maximum comfort (and for this code to not do crazy stupid things):
    please rename your project folder with the current 'tarX' you are working on.
    I don't know what happens if you don't and I take 0 responsibility for it.
    Don't try taking off the safety check. It's meant to protect you from blowing off your foot.

    P.S. If you want to contribute something please feel free to use a .env file and just continue working on it.
    """


    # full path to project directory (r"C:\...\tarX") X={1, 2, 3, ..., n}
    source = r"C:\...\tarX"        # change this to your path to project
    source = os.getenv("source")   # DELETE THIS LINE

    # PERSONAL DETAILS: (ex. "John Doe-123412341")
    first_person = "<FIRST_PERSON_NAME>-<FIRST_PERSON_ID_NUMBER>"
    second_person = "<SECOND_PERSON_NAME>-<SECOND_PERSON_NAME>"

    first_person = os.getenv("first_person")   # DELETE THIS LINE
    second_person = os.getenv("second_person") # DELETE THIS LINE

    # FTP DETAILS:
    ftp_server = "<RUPPIN_SERVER_IP>"          # change to RUPPIN SERVER IP (xxx.xxx.xxx.xxx)
    ftp_username = "<FTP-GROUP_NAME>"          # change to: "cgroupX"
    ftp_password = "<FTP-GROUP_PASSWORD>"      # change to "cgroup_PASS"

    ftp_server = os.getenv("ftp_server")       # DELETE THIS LINE
    ftp_username = os.getenv("ftp_username")   # DELETE THIS LINE
    ftp_password = os.getenv("ftp_password")   # DELETE THIS LINE


    source = normalize_path(source)

    # Mandatory safety check
    tar = os.path.basename(source)
    remote_directory = f"/{ftp_username}/test1/{os.path.basename(source)}/"
    safety_check(tar)
    if not check_ftp_login(ftp_server, ftp_username, ftp_password, remote_directory):
        return


    clear_ftp_directory(ftp_server, ftp_username, ftp_password, remote_directory, verbose=False)

    zip_path = create_zip_archive(source=source, verbose=False)

    if zip_path:
        upload_folder_to_ftp(ftp_server, ftp_username, ftp_password, source, remote_directory)
        pass

    # Output project links (for email mainly)

    print(f"\n\nTitle: {ftp_username} {tar} {first_person}, {second_person}")
    print("ClientRuppin@gmail.com")
    print(f"ZIP: https://proj.ruppin.ac.il/{ftp_username}/test1/{tar}/{tar}.zip")
    print(f"Web: https://proj.ruppin.ac.il/{ftp_username}/test1/{tar}/")

if __name__ == "__main__":
    main()

#!/usr/bin/env python
# -*- coding: utf-8 -*-

# NOTE Windows-specific for now

import sys
import os
import signal
import json
import subprocess
import time
import hashlib
import shutil
from pathlib import Path

# Find the closest path with a yagc directory
working_dir = os.getcwd()
yagc_dir = os.path.join(working_dir, 'yagc')

while (len(sys.argv) < 2 or sys.argv[1] != 'init') and not os.path.isdir(yagc_dir):
    if working_dir == '/' or working_dir.endswith(':\\'):
        # There's no yagc directory in the entire tree
        print("You're not in a YAGC repository -- try running `yagc init` first.")
        sys.exit(-1)
    
    working_dir = os.path.dirname(working_dir)
    yagc_dir = os.path.join(working_dir, 'yagc')

commits_dir = os.path.join(yagc_dir, 'commits')

relative_yagc_files = ['staged.json', 'commits.json', 'status.json', 'tracked.json']
yagc_files = [os.path.join(yagc_dir, filename) for filename in relative_yagc_files]

staged_filename, commits_filename, status_filename, tracked_filename = yagc_files

handlers = {}
handler_descs = {}
handler_long_descs = {}
handler_syntaxes = {}
handler_options = {}
def handler(desc, long_desc, syntax, options={}):
    def inner(func):
        handlers[func.__name__] = func
        handler_descs[func.__name__] = desc.strip()
        handler_long_descs[func.__name__] = long_desc.strip()
        handler_syntaxes[func.__name__] = syntax.strip()
        handler_options[func.__name__] = options
        return func
    return inner

def do_help(command=None, *args):
    if command:
        print('Syntax:', handler_syntaxes[command])
        print()
        print(handler_long_descs[command])
        
        if handler_options[command]:
            print()
            print('Options:')
            
            for option, option_help in handler_options[command].items():
                if isinstance(option, tuple):
                    option_str = ', '.join(option)
                else:
                    option_str = option
                
                print(' ', option_str + ':', option_help)
    else:
        print('Syntax: yagc <command> [args...]')
        print('Where <command> is one of:')
        
        for handler_name in handlers:
            print('  ', handler_name, ' ' * (20 - len(handler_name)), handler_descs[handler_name])
        
        print('Use `yagc help <command>` for more information on a specific command.')

handlers['help'] = do_help
handler_descs['help'] = 'Show this help message'
handler_long_descs['help'] = '''
Show more information about a YAGC command. For example, `yagc help help` will
print this help message.
'''.strip()
handler_syntaxes['help'] = 'yagc help [command]'
handler_options['help'] = {'command': 'A YAGC command to get help about'}

def strip_working_dir(filename):
    return filename[len(working_dir) + 1:] if filename.startswith(working_dir) else filename

def is_head():
    with open(status_filename) as status_file:
        status = json.load(status_file)
    return status['head']

@handler('Initialize a new YAGC repository', '''
Initialize a new YAGC repository in the current working directory. This command
will create a new `yagc` directory in the current working directory, allowing
the current working directory to be used as a YAGC repository.

This command will do nothing if the repository has already been initialized,
and to get around the DDSB's insane permissions management, will work even if
the `yagc` directory is present and empty.
''', 'yagc init')
def init(*args):
    # Initialize the directory -- make a yagc directory & populate it
    
    try:
        try:
            os.mkdir(yagc_dir)
        except OSError:
            # Get past DDSB's insane permissions management -- ignore if the directory's empty
            if os.listdir(yagc_dir):
                raise
        
        for yagc_filename in yagc_files:
            with open(yagc_filename, 'w') as yagc_file:
                if yagc_filename.endswith('status.json'):
                    json.dump({'head': True}, yagc_file)
                else:
                    json.dump([], yagc_file)
        
        os.mkdir(commits_dir)
    except OSError:
        # The directory already exists
        print('Project already initialized -- delete the yagc folder if you want to reinitialize')

@handler('Stage a file for commit', '''
Stage a file or files for commit. When the staged files are committed with
`yagc commit`, all files added using this command will be committed and the
staged files will be reset -- no files will be staged.

This command does nothing if the file has already been staged.
''', 'yagc add <filename> [filenames...]', {'filename(s)': 'The relative filename(s) to stage for commit'})
def add(*filenames):
    if not filenames:
        do_help('add')
    
    if not is_head():
        print('Cannot add files when HEAD is not checked out.')
        return
    
    def get_abs_path(fn):
        return os.path.join(working_dir, os.path.normpath(filename))
    
    for filename in filenames:
        # Add filename to yagc/staged.json if it's not already added
        filename = get_abs_path(filename)
        
        # Check that the file exists
        if not os.path.isfile(filename):
            print("File %s doesn't exist!" % filename)
            continue
        
        with open(staged_filename, 'r+') as staged_file:
            staged = json.load(staged_file)
            
            if filename in staged:
                print(filename, 'already staged!')
            else:
                staged_file.seek(0) # Now we can write
                
                staged.append(filename)
                json.dump(staged, staged_file)
                
                staged_file.truncate() # Overwrite anything that wasn't written

@handler('Unstage a file', '''
Unstage a file. The file's changes will no longer be committed on `yagc commit`,
but will still be tracked if it had been committed previously.

This command does nothing if the file is not staged, or if HEAD is not checked
out.
''', 'yagc remove <filename>', {'filename': 'The relative filename to unstage'})
def remove(filename, *args):
    # Remove filename from yagc/staged.json if it's in there
    
    if not is_head():
        print('Cannot remove files when HEAD is not checked out')
        return
    
    filename = os.path.join(working_dir, filename)
    
    with open(staged_filename, 'r+') as staged_file:
        staged = json.load(staged_file)
        
        if filename in staged:
            staged_file.seek(0) # Now we can write
            
            staged.remove(filename)
            json.dump(staged, staged_file)
            
            staged_file.truncate() # Overwrite anything that wasn't written
        else:
            print(filename, 'not staged!')

@handler('Commit changes in staged files to the repository', '''
Commits changes in staged files to the repository. This command records changes
in all files staged using `yagc add`; the version can then be retrieved using
`yagc checkout`.

When this command is run, a system-dependant editor choosing window will pop up,
prompting you to choose an editor. Choose a plain text editor such as Notepad in
which to enter a commit message. When the file is saved, the commit message will
have been entered; at that point, the editor should close. If it doesn't, it's
because the DDSB won't let us kill a process; you can then close the editor
manually.

A commit hash is generated for each commit. This hash is important because it or
a prefix of it can be used to retrieve the commit. The commit hash can be
retrieved using `yagc log`.

This command does nothing if no files are staged for commit, or if HEAD is not
checked out.

NOTE: sometimes a PermissionError will occur upon saving the file. If this
happens, simply rerun `yagc commit` and everything will work properly.
''', 'yagc commit')
def commit(*args):
    if not is_head():
        print('Cannot commit when HEAD is not checked out')
        return
    
    # Get the staged files
    with open(staged_filename) as staged_file:
        staged = json.load(staged_file)
    
    # Get the tracked files
    with open(tracked_filename) as tracked_file:
        tracked = set(json.load(tracked_file))
    
    # Find deletions
    deletions = {filename for filename in tracked if not os.path.isfile(filename)}
    
    if not staged and not deletions:
        print('There are no staged files -- try using `yagc add` first.')
        return
    
    # Make the commit message file
    msg_filename = os.path.join(yagc_dir, 'COMMIT_MSG')
    Path(msg_filename).touch()
    
    # Open default editor to enter a commit message
    # NOTE Windows-specific
    print('Opening editor to enter commit message...')
    print("(Choose an editor. When you're done with the commit message, save, then exit the program)")
    editor = subprocess.Popen(['start', '/WAIT', msg_filename], shell=True)
    
    # Wait until it's changed
    # NOTE Also Windows-specific
    start_time = os.path.getctime(msg_filename)
    while start_time == os.path.getmtime(msg_filename):
        time.sleep(0.25)
    
    # Kill the editor
    try:
        os.kill(editor.pid, signal.SIGTERM)
    except:
        # Turns out that the DDSB won't let us kill a process. Gah.
        pass
    
    # Get the commit message
    with open(msg_filename) as msg_file:
        msg = msg_file.read()
    
    # Delete the commit message file
    first = True
    while True:
        # Work around a weird PermissionError
        try:
            os.remove(msg_filename)
        except PermissionError:
            if first:
                print('Working around permissions error: waiting...', end='')
                first = False
            else:
                print('.', end='')
            
            time.sleep(0.5)
        else:
            print()
            break
    
    # Generate a commit hash based on the current time
    hash_ = hashlib.sha1()
    hash_.update(str(time.time()).encode('utf-8'))
    hash_ = hash_.hexdigest()
    
    commit = {
        "msg": msg,
        "hash": hash_
    }
    
    # Add the commit directory
    commit_dir = os.path.join(commits_dir, hash_)
    os.mkdir(commit_dir)
    
    # Wipe staged.json
    with open(staged_filename, 'w') as staged_file:
        json.dump([], staged_file)
    
    # Copy the staged files to the commit directory
    for filename in staged:
        # Handle directories
        relative_filename = strip_working_dir(filename)
        tree = relative_filename.split(os.sep)
        
        file_dir = commit_dir
        
        if len(tree) > 1:
            for directory in tree[:-1]:
                file_dir = os.path.join(file_dir, directory)
                os.mkdir(file_dir)
        
        shutil.copy(filename, file_dir)
    
    # Add the commit to commits.json
    with open(commits_filename, 'r+') as commits_file:
        commits = json.load(commits_file)
        commits.append(commit)
        
        commits_file.seek(0)
        json.dump(commits, commits_file)
        commits_file.truncate()
    
    if len(commits) > 1:
        # Copy the tracked files that aren't staged from the previous commit (and aren't deleted)
        prev_commit_dir = os.path.join(commits_dir, commits[-2]['hash'])
        for filename in tracked - set(staged) - set(deletions):
            try:
                # Add directories
                stripped_filename = strip_working_dir(filename)
                tree = stripped_filename.split(os.sep)
                file_dir = commit_dir
                
                if len(tree) > 1:
                    for directory in tree[:-1]:
                        file_dir = os.path.join(file_dir, directory)
                        os.mkdir(file_dir)
                
                shutil.copy(os.path.join(prev_commit_dir, stripped_filename), file_dir)
            except Error as e:
                # Tracked files are wrong?
                print('The tracked files are wrong. Wut.')
                print('Exception:', e)
    
    # Update the tracked files
    tracked.update(staged)
    with open(tracked_filename, 'w') as tracked_file:
        json.dump(list(tracked), tracked_file)
    
    print('Commit hash:', hash_)

@handler('Display a summary of all commits', '''
Display a summary of all commits. This command will print the commit messages
and hashes of all commits, as well as a total number.

If --short or -s is specified, an abridged version of the commit log will be
printed. Only the first line of the commit message will be printed, instead of
the entire message.
''', 'yagc log [--short | -s]',  {('--short', '-s'): 'Print an abridged version of the commit log'})
def log(*args):
    short = len(args) > 0 and args[0] in ['--short', '-s']
    
    # Get the commits
    with open(commits_filename) as commits_file:
        commits = json.load(commits_file)
    
    print('{} commit{}'.format(len(commits), '' if len(commits) == 1 else 's'))
    if commits:
        print()
    
    for commit in commits:
        if short:
            head = commit['msg'].split('\n')[0]
            print(commit['hash'], head)
        else:
            print('Commit', commit['hash'])
            print()
            print(commit['msg'])
            
            if commit != commits[-1]:
                print()
                print('---')
                print()

@handler("Display YAGC's current status -- staged files, etc.", '''
Display the current status of the YAGC repository. This command will print a
list of staged files, as well as whether HEAD is checked out.
''', 'yagc status')
def status(*args):
    print('Status of repository at %s:' % working_dir)
    
    # Get the staged files
    with open(staged_filename) as staged_file:
        staged = json.load(staged_file)
    
    # Get the status file
    with open(status_filename) as status_file:
        status = json.load(status_file)
    
    # Pretty-print it
    print('{} file{} staged for commit{}'.format(
        len(staged) if staged else 'No',
        '' if len(staged) == 1 else 's',
        ':' if staged else '.',
    ))
    
    for filename in staged:
        print('-', strip_working_dir(filename))
    
    
    if status['head']:
        print('HEAD is checked out.')
    else:
        print('HEAD is not checked out; some functionality unavailable')

def get_commit_from_hash_prefix(prefix):
    # Get the list of commits
    with open(commits_filename) as commits_file:
        commits = json.load(commits_file)
    
    commit = False
    for filed_commit in commits:
        if filed_commit['hash'].startswith(prefix.lower()):
            if commit:
                print(prefix, 'is ambiguous. Use a more specific commit hash prefix.')
                return
            commit = filed_commit
    
    if not commit:
        return 'no valid commit'
    
    return commit

@handler('Restore the repository to the state it was in a certain commit', '''
Restore the repository to the state it was in a certain commit. This command
will change the repository to match its state at the time of the commit
specified by the commit hash.

`commit_hash` can either be the prefix of a commit hash, or 'HEAD'. If it is a
non-ambigious prefix of a commit hash, the commit referenced by that hash will
be checked out as specified above.

If `commit_hash` is 'HEAD', the most recent commit will be checked out.

Since you can only modify the repository at the most recent version, some
commands, such as `yagc add`, `yagc remove`, and `yagc commit`, are only
available when HEAD is checked out.

If you check out a commit (that isn't HEAD) and have uncommitted changes in
tracked files, they will be lost. You will be asked if you want to check out
now, or go back and commit or revert your changes before checking out any
commit.
''', 'yagc checkout <commit_hash> [--quiet | -q]',
{
    'commit_hash': 'The hash prefix of the commit to checkout, or HEAD',
    ('-q', '--quiet'): "Don't warn that uncommitted changes will be lost"
})
def checkout(commit_hash, *args):
    head = commit_hash.upper() == 'HEAD'
    
    # Get the tracked files
    with open(tracked_filename) as tracked_file:
        tracked = json.load(tracked_file)
    
    # Get the list of commits
    with open(commits_filename) as commits_file:
        commits = json.load(commits_file)
    
    if head:
        commit = commits[-1]
    else:
        commit = get_commit_from_hash_prefix(commit_hash)
        
        if commit == 'no valid commit':
            print(commit_hash, 'is not a valid commit hash prefix or `HEAD`.')
            return
        
        # Warn the user about losing uncommitted changes
        if not (len(args) > 0 and args[0] in ['--quiet', '-q']):
            print('Warning! Uncommitted changes will be lost!')
            cont = input('Do you want to proceed? (y/N) ')
            
            if cont.upper() != 'Y':
                print('Aborting checkout')
                return
    
    # Remove all tracked files from the working directory -- for handling deletions
    for filename in tracked:
        try:
            os.remove(filename)
        except FileNotFoundError:
            # The file was removed -- ignore
            pass
    
    # Find all directories where all the files inside are either tracked or one of those directories
    tracked_dirs = []
    for path, directories, filenames in os.walk(working_dir, topdown=False):
        if path == working_dir or os.sep + 'yagc' in path or os.sep + 'yagc' + os.sep in path:
            continue
        
        for filename in filenames:
            if filename not in tracked:
                continue
        
        for directory in directories:
            if directory not in tracked_dirs:
                continue
        
        tracked_dirs.append(path)
    
    # Remove all of them
    for directory in tracked_dirs:
        try:
            os.rmdir(directory)
        except:
            # tracked_dirs is in a weird order -- ignore
            pass
    
    # Copy the files from the commit directory to the working directory
    commit_dir = os.path.join(commits_dir, commit['hash'])
    for path, directories, filenames in os.walk(commit_dir):
        if path == commit_dir:
            file_dir = working_dir
        else:
            stripped = path[len(commit_dir) + 1:]
            file_dir = os.path.join(working_dir, stripped)
        
        if path != commit_dir:
            try:
                os.mkdir(file_dir)
            except:
                # The directory wasn't removed -- ignore
                pass
        
        for filename in filenames:
            shutil.copy(os.path.join(path, filename), file_dir)
    
    # Update status.json
    with open(status_filename, 'r+') as status_file:
        status = json.load(status_file)
        
        status_file.seek(0)
        
        status['head'] = head
        json.dump(status, status_file)
        
        status_file.truncate()
    
    print('Checked out', 'HEAD' if head else 'commit {}'.format(commit['hash']))

@handler('Remove all commits after a certain commit', '''
Restore the repository to the state it was in a certain commit and remove all
commits after.

This command is similar to `yagc checkout` in that it restores the repository to
the state in was in a particular commit. However, this command will remove all
commits after that commit, making that commit the new HEAD.

`commit_hash` can either be the prefix of a commit hash, or 'HEAD'. If it is a
non-ambigious prefix of a commit hash, the commit referenced by that hash will
be checked out as specified above.

Since the repository can only be modified at the most recent commit, this
command will fail if HEAD is not checked out.
''', 'yagc reset <commit_hash>', {'commit_hash': 'The hash prefix of the commit to reset to'})
def reset(hash_prefix, *args):
    if not is_head():
        print('Cannot reset when HEAD is not checked out.')
    
    commit = get_commit_from_hash_prefix(hash_prefix)
    
    if commit == 'no valid commit':
        print(hash_prefix, 'is not a valid commit hash prefix.')
        return
    
    print('WARNING! All commits before', commits['hash'], 'will be lost!')
    print('History will be lost. This cannot be undone!')
    cont = input('Do you want to proceed? (y/N) ')
    
    if cont.upper() != 'Y':
        print('Aborting reset')
        return
    
    checkout(hash_prefix, '-q') # HACK
    
    # Remove all commits greater
    with open(commits_filename, 'r+') as commits_file:
        commits = json.load(commits_file)
        commit_idx = commits.index(commit)
        new_commits = list(commits[:commit_idx + 1])
        
        commits_file.seek(0)
        json.dump(new_commits, commits_file)
        commits_file.truncate()
    
    # Set HEAD to True
    with open(status_filename, 'r+') as status_file:
        status = json.load(status_file)
        status[head] = True
        
        status_file.seek(0)
        json.dump(status, status_file)
        status_file.truncate()
    
    print('Successfully reset')

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] in handlers:
        handlers[sys.argv[1]](*sys.argv[2:])
    else:
        do_help(*sys.argv[2:])
        sys.exit(-1)

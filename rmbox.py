#!/usr/bin/env python3

import argparse
import urllib.request
import urllib.error
import email
import subprocess
import os
import sys
import re
import datetime

def get_mbox_data(source):
    """Fetches mbox data from a URL or reads from a local file."""

    if source.startswith('http://') or source.startswith('https://'):
        print(f"Fetching from URL: {source}...")
        try:
            req = urllib.request.Request(
                source,
                headers={'User-Agent': 'rmbox/0.1-init'}
            )
            with urllib.request.urlopen(req) as response:
                return response.read().decode('utf-8', errors='replace')
        except urllib.error.URLError as e:
            print(f"Error fetching URL: {e}")
            sys.exit(1)
    else:
        print(f"Reading from file: {source}...")
        if not os.path.exists(source):
            print(f"Error: File '{source}' does not exist.")
            sys.exit(1)
        try:
            with open(source, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception as e:
            print(f"Error reading file: {e}")
            sys.exit(1)

def build_reply_template(raw_email):
    """Parses original email and generates a reply template. Returns (template, subject)."""

    headers = []
    msg = email.message_from_string(raw_email)
    headers.append(f"To: {msg.get('From', '')}")
    
    ccs = []
    if msg.get('To'):
        ccs.append(msg.get('To').replace('\n', ' ').replace('\r', '').strip())
    if msg.get('Cc'):
        ccs.append(msg.get('Cc').replace('\n', ' ').replace('\r', '').strip())
        
    if ccs:
        headers.append(f"Cc: {', '.join(ccs)}")
        
    subj = msg.get('Subject', '')
    if not subj.lower().startswith('re:'):
        subj = 'Re: ' + subj
    clean_subj = subj.replace(chr(10), '').replace(chr(13), '')
    headers.append(f"Subject: {clean_subj}")
    
    msg_id = msg.get('Message-ID', '')
    headers.append(f"In-Reply-To: {msg_id}")
    
    refs = msg.get('References', '')
    headers.append(f"References: {refs} {msg_id}" if refs else f"References: {msg_id}")
    
    payload = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                payload = part.get_payload(decode=True).decode('utf-8', 'replace')
                break
    else:
        payload = msg.get_payload(decode=True).decode('utf-8', 'replace')

    quoted_body = "\n".join(f"> {line}" for line in payload.splitlines())
    
    template = "\n".join(headers) + "\n\n" + quoted_body + "\n"
    return template, clean_subj

def get_save_directory():
    """Generates and ensures the ~/.rmbox/YYYY-MM-DD/ directory exists"""

    today = datetime.datetime.now().strftime("%Y-%m-%d")
    rmbox_dir = os.path.expanduser(f"~/.rmbox/{today}")
    os.makedirs(rmbox_dir, exist_ok=True)
    return rmbox_dir

def main():
    parser = argparse.ArgumentParser(description="Reply to mbox patches easily.")
    parser.add_argument("source", nargs="?", help="A URL to a raw mbox file or a local mbox file")
    parser.add_argument("--resume", metavar="FILE", help="Re-open an existing drafted reply")
    parser.add_argument("--reply", action="store_true", help="Send the reply via git send-email on save")
    parser.add_argument("--len", type=int, default=80, help="Maximum line length while composing (default: 80)")
    
    args = parser.parse_args()
    
    if not args.source and not args.resume:
        parser.error("You must provide either a source URL/file or use --resume FILE.")
    if args.source and args.resume:
        parser.error("Cannot use both a source and --resume at the same time.")

    is_new_draft = False

    if args.resume:
        target_path = os.path.expanduser(args.resume)
        if not os.path.exists(target_path):
            print(f"Error: Draft '{target_path}' does not exist.")
            sys.exit(1)
        print(f"Resuming draft: {target_path}")
    else:
        # Fetch, parse and generate new draft
        is_new_draft = True
        raw_email = get_mbox_data(args.source)
        template, raw_subj = build_reply_template(raw_email)
        
        # Create safe filename and directory
        safe_name = re.sub(r'[^A-Za-z0-9]+', '-', raw_subj).strip('-')
        if not safe_name:
            safe_name = "reply"
        safe_name = safe_name[:100] + ".eml"
        
        save_dir = get_save_directory()
        target_path = os.path.join(save_dir, safe_name)
        
        # Avoid overwriting existing drafts with the exact same subject today
        base_name = safe_name[:-4]
        counter = 1
        while os.path.exists(target_path):
            target_path = os.path.join(save_dir, f"{base_name}-{counter}.eml")
            counter += 1
            
        with open(target_path, 'w') as f:
            f.write(template)

    # Capture modification time (mtime) before opening editor
    initial_mtime = os.path.getmtime(target_path)
    
    # Configure Editor Wrapping (defaults to vim)
    editor = os.environ.get('EDITOR', 'vim')
    cmd = [editor]
    
    # Pass filetype=mail to protect diff quotes and apply custom textwidth
    if 'vim' in editor or 'nvim' in editor:
        cmd.extend(['-c', 'set filetype=mail', '-c', f'set textwidth={args.len}'])
    elif 'nano' in editor:
        cmd.extend(['-r', str(args.len)])
        
    cmd.append(target_path)
    
    subprocess.call(cmd)
    
    # Capture mtime after editor closes
    final_mtime = os.path.getmtime(target_path)
    
    # Detect :wq (updates mtime) vs :q! (leaves mtime unchanged)
    if initial_mtime == final_mtime:
        print("No changes detected (discarded on exit).")
        if is_new_draft:
            os.remove(target_path)
            print("Draft deleted.")
        else:
            print("Existing draft left untouched.")
        sys.exit(0)
        
    print(f"Draft saved to {target_path}")
    
    # Execution
    if args.reply:
        print("Handing off to git send-email...")
        subprocess.call(['git', 'send-email', '--assume-yes', target_path])
        print("Done.")

if __name__ == "__main__":
    main()

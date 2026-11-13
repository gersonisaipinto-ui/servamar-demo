"""Access control for SERVAMAR on a trusted office LAN (no internet exposure)."""
import hashlib, hmac, json, os, secrets
from pathlib import Path

CONFIG_NAME='acceso_red_local.json'
ITERATIONS=600_000

def lan_config_path(data_dir):
    return Path(data_dir)/CONFIG_NAME

def lan_is_enabled(data_dir):
    try:
        c=json.loads(lan_config_path(data_dir).read_text(encoding='utf-8'))
        return c.get('enabled') is True and bool(c.get('username')) and bool(c.get('password_hash'))
    except (FileNotFoundError, ValueError, OSError):
        return False

def configure_lan(data_dir, username, password):
    username=username.strip()
    if not 3<=len(username)<=64 or not username.replace('_','').replace('-','').isalnum():
        raise ValueError('Usuario: 3-64 caracteres alfanumericos, guion o guion bajo')
    if len(password)<6:
        raise ValueError('La contrasena debe tener 6 caracteres como minimo')
    salt=os.urandom(16)
    dk=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,ITERATIONS)
    config={'enabled':True,'username':username,'salt':salt.hex(),
            'password_hash':dk.hex(),'iterations':ITERATIONS}
    dest=lan_config_path(data_dir);dest.parent.mkdir(parents=True,exist_ok=True)
    temp=dest.with_suffix('.tmp')
    temp.write_text(json.dumps(config,indent=2),encoding='utf-8')
    os.replace(temp,dest)
    return dest

def check_lan_credentials(data_dir, username, password):
    try:
        c=json.loads(lan_config_path(data_dir).read_text(encoding='utf-8'))
        salt=bytes.fromhex(c['salt']); target=bytes.fromhex(c['password_hash'])
        iteration_count=int(c['iterations'])
        if not c.get('enabled') or iteration_count<100_000 or iteration_count>1_000_000:
            return False
        candidate=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,iteration_count)
        return hmac.compare_digest(str(username),str(c['username'])) and hmac.compare_digest(candidate,target)
    except (OSError,ValueError,KeyError,TypeError):
        return False

"""Private Supabase REST adapter. Browser receives only short-lived API capabilities."""
import hashlib
import io
import json
import subprocess
import tempfile
from urllib.parse import quote
import httpx
from PIL import Image
from server.repositories.postgres import fail

class MediaStore:
    def __init__(self, settings):
        self.base = settings.supabase_url + '/storage/v1'
        self.bucket = settings.bucket
        self.headers = {'Authorization':'Bearer '+settings.service_key,'apikey':settings.service_key}

    def path(self,key):
        return quote(self.bucket,safe='')+'/'+quote(key,safe='/')

    def request(self,method,path,**kwargs):
        headers={**self.headers, **kwargs.pop("headers", {})}
        with httpx.Client(timeout=60) as client:
            r = client.request(method,self.base+path,headers=headers,**kwargs)
            r.raise_for_status()
            return r

    def write(self,key,data,mime):
        self.request('POST','/object/'+self.path(key),content=data,headers={'Content-Type':mime},
                     # Only server-generated keys; no upsert or overwrite.
                     )

    def read_private(self,key):
        return self.request('GET','/object/authenticated/'+self.path(key)).content

    def delete(self,key):
        self.request('DELETE','/object/'+quote(self.bucket,safe=''),json={'prefixes':[key]})

    def sign_read(self,key):
        r=self.request('POST','/object/sign/'+self.path(key),json={'expiresIn':60}).json()
        return self.base+r['signedURL']

def validate_media(data, attachment):
    if len(data) != attachment['byte_size'] or hashlib.sha256(data).hexdigest() != attachment['checksum']:
        fail(422,'checksum_mismatch','Uploaded bytes do not match size/checksum')
    mime=attachment['mime_type']
    if mime.startswith('image/'):
        if len(data)>10*1024*1024:
            fail(413,'media_limit','Images must be at most 10 MB')
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format != {'image/png':'PNG','image/jpeg':'JPEG'}[mime] or image.width*image.height>40_000_000:
                    raise ValueError()
                image.verify()
        except Exception:
            fail(415,'invalid_media','Image cannot be decoded as the declared type')
    else:
        # ffprobe inspects actual container/codec/duration, never the filename.
        with tempfile.NamedTemporaryFile() as f:
            f.write(data); f.flush()
            try:
                r=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',f.name],capture_output=True,timeout=20,check=True)
                info=json.loads(r.stdout)
                duration=float(info['format']['duration'])
                formats=set(info['format']['format_name'].split(','))
                expected={'audio/mpeg':{'mp3'},'audio/mp4':{'mov','mp4','m4a'},'audio/wav':{'wav'},'audio/webm':{'webm','matroska'}}[mime]
                if not formats & expected or not any(s['codec_type']=='audio' for s in info['streams']):
                    raise ValueError()
                if not 0<duration<=900:
                    fail(413,'media_limit','Audio must be at most 15 minutes')
            except (subprocess.SubprocessError,KeyError,ValueError):
                fail(415,'invalid_media','Audio cannot be decoded as the declared type')
            except FileNotFoundError:
                fail(503,'media_validator_unavailable','Install ffprobe on the API host')

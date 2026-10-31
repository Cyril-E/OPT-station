"""Opt-in qualification against a real Caddy binary (no system installation)."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

import httpx
import pytest

ROOT=Path(__file__).parents[1]
CADDY=os.getenv('OPT_STATION_CADDY') or shutil.which('caddy')


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]


@pytest.mark.skipif(not CADDY,reason='Set OPT_STATION_CADDY to qualify the real local HTTPS gateway')
def test_real_gateway_certificates_headers_redirects_mcp_and_restart(tmp_path):
    spec=importlib.util.spec_from_file_location('gateway_install',ROOT/'deploy/install-https.py')
    installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
    backend,plain,secure,legacy=port(),port(),port(),port()
    while len({backend,plain,secure,legacy})!=4:backend,plain,secure,legacy=port(),port(),port(),port()
    config=tmp_path/'Caddyfile'
    config.write_text(installer.caddyfile(['localhost','127.0.0.1'],backend,plain,secure,legacy))
    environment={**os.environ,'XDG_DATA_HOME':str(tmp_path/'state'),'XDG_CONFIG_HOME':str(tmp_path/'config')}
    root=tmp_path/'state/caddy/pki/authorities/local/root.crt'
    metadata=tmp_path/'https.json'
    metadata.write_text(json.dumps({'version':1,'url':f'https://localhost:{secure}',
                                   'aliases':[f'https://127.0.0.1:{secure}'],'ca_cert':str(root)}))
    log=open(tmp_path/'gateway.log','w+')
    gateway=app=None
    try:
        subprocess.run([CADDY,'validate','--config',str(config),'--adapter','caddyfile'],env=environment,check=True,stdout=log,stderr=log)
        # This is the same provisioning step used by the system installer.
        assert root.exists()
        certificate=root.read_bytes()
        app=subprocess.Popen([sys.executable,'-m','openprinttag_app','--mode','simulation','--data-dir',str(tmp_path/'data'),
                              '--port',str(backend),'--https-config',str(metadata)],cwd=ROOT,stdout=log,stderr=log)
        gateway=subprocess.Popen([CADDY,'run','--config',str(config),'--adapter','caddyfile'],env=environment,stdout=log,stderr=log)
        ctx=ssl.create_default_context(cafile=str(root))
        url=f'https://localhost:{secure}'
        with httpx.Client(verify=ctx,trust_env=False,timeout=3) as client:
            deadline=time.monotonic()+25
            while True:
                try:
                    status=client.get(url+'/api/status');status.raise_for_status();break
                except (httpx.HTTPError,OSError):
                    if time.monotonic()>deadline:
                        log.flush();raise AssertionError((tmp_path/'gateway.log').read_text())
                    time.sleep(0.1)
            assert status.json()['local_station'] is True
            # Caddy must overwrite user-supplied addresses and protocols.
            spoof=client.get(url+'/api/status',headers={'X-Forwarded-For':'192.0.2.123','X-Forwarded-Proto':'http'})
            assert spoof.json()['local_station'] is True
            assert client.get(url+'/api/configuration/https').json()['secure'] is True
            assert client.get(url+'/https/certificate').content==certificate
            assert client.get(f'https://127.0.0.1:{secure}/api/status').status_code==200
            with httpx.Client(trust_env=False,timeout=3) as untrusted:
                with pytest.raises(httpx.ConnectError):untrusted.get(url+'/api/status')
            public=f'http://localhost:{plain}'
            for base in (public, f'http://localhost:{legacy}'):
                home=client.get(base+'/')
                assert home.status_code==302 and home.headers['location']=='/https'
            assert client.get(public+'/https').status_code==200
            assert client.get(f'http://localhost:{legacy}/https/certificate').content==certificate
            redirect=client.get(public+'/api/status')
            assert redirect.status_code==308 and redirect.headers['location']==url+'/api/status'
            denied=client.put(public+'/api/configuration/network',json={'mode':'full'})
            assert denied.status_code==308  # The HTTP gateway never dispatches actions.
            assert client.get(url+'/api/status').json()['network']['mode']=='inventory'
            client.put(url+'/api/configuration/mcp',json={'enabled':True,'revision':0}).raise_for_status()
            message={'jsonrpc':'2.0','id':1,'method':'initialize','params':{
                'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'HTTPS test','version':'1'}}}
            response=client.post(url+'/mcp',json=message,headers={'Accept':'application/json, text/event-stream','Origin':url})
            response.raise_for_status();assert response.json()['result']['serverInfo']['name']=='OPT Station'
            assert client.get(url+'/api/configuration/mcp').json()['endpoint']==url+'/mcp'
            # The same gateway flushes live notifications while the tab stays in the background.
            with client.stream('GET',url+'/api/printer/events') as stream:
                stream.raise_for_status()
                assert stream.headers['content-type'].startswith('text/event-stream')
                lines=stream.iter_lines()
                assert next(lines)=='event: status'
                assert next(lines).startswith('data: ')
            gateway.terminate();gateway.wait(timeout=10)
            gateway=subprocess.Popen([CADDY,'run','--config',str(config),'--adapter','caddyfile'],env=environment,stdout=log,stderr=log)
            deadline=time.monotonic()+15
            while True:
                try:
                    response=client.get(url+'/api/status');response.raise_for_status();break
                except httpx.HTTPError:
                    if time.monotonic()>deadline:raise
                    time.sleep(0.1)
            assert root.read_bytes()==certificate
    finally:
        for process in (gateway,app):
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        log.close()

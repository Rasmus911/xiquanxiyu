from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def test_versioned_entrypoint_has_exact_checkpoint_and_no_old_path_defaults():
    script=(ROOT/'scripts/invoke-desktop-050.ps1').read_text(encoding='utf-8-sig')
    assert 'desktop050-stage-' in script and 'desktop050-cutover-' in script
    assert 'UPDATE 0.5.0' in script and 'desktop_050_deploy.py' in script
    assert 'Invoke-TokenNative' in script and 'TimeoutSeconds' in script
    assert 'Read-Host' not in script.split("if($Mode-in @('preflight','all')){")[1].split('$confirmation')[0]

def test_private_cleanup_never_exposes_owner_to_api():
    config=(ROOT/'deploy/cloud/docker-compose.prod.yml').read_text(encoding='utf-8')
    api=config.split('\n  api:\n')[1].split('\n  receipt-cleanup:\n')[0]
    worker=config.split('\n  receipt-cleanup:\n')[1].split('\n  maintenance:\n')[0]
    assert 'networks: [backend]' in worker and '\n    ports:' not in worker and '\n    expose:' not in worker
    assert '\n      MAINTENANCE_DATABASE_URL:' not in api
    assert 'entrypoint: ["python", "-m", "app.receipt_cleanup_worker"]' in worker

def test_origin_health_keeps_tls_uses_http1_and_no_remote_public_dependency():
    script=(ROOT/'deploy/cloud/scripts/desktop_050_deploy.py').read_text()
    assert "'--http1.1'" in script and "'--resolve','api.pqxqxy.xyz:443:127.0.0.1'" in script
    assert "'--insecure'" not in script and "'-k'" not in script

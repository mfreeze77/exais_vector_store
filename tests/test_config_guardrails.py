import pytest
from svs_common.config import Settings, validate_production_guardrails

def test_production_guard_rejects_dev_mode_and_default_pepper():
    s = Settings(svs_env='prod', svs_dev_mode=True, svs_api_key_pepper='change-me-in-prod')
    with pytest.raises(RuntimeError) as exc:
        validate_production_guardrails(s)
    msg = str(exc.value)
    assert 'SVS_DEV_MODE' in msg
    assert 'SVS_API_KEY_PEPPER' in msg

def test_local_guard_allows_dev_mode():
    s = Settings(svs_env='local', svs_dev_mode=True, svs_api_key_pepper='change-me-in-prod')
    validate_production_guardrails(s)

def test_production_guard_requires_tls_verification_for_https_opensearch():
    s = Settings(
        svs_env='prod',
        svs_dev_mode=False,
        svs_api_key_pepper='x' * 64,
        opensearch_url='https://opensearch.internal:9200',
        opensearch_verify_certs=False,
    )
    with pytest.raises(RuntimeError) as exc:
        validate_production_guardrails(s)
    assert 'OPENSEARCH_VERIFY_CERTS' in str(exc.value)

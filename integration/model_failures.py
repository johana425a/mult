"""Safe model diagnostics and bounded recovery before any output is delivered."""
from __future__ import annotations
import asyncio
import logging
import uuid

log = logging.getLogger(__name__)


def failure_details(exc):
    from fastapi import HTTPException
    from deeptutor.services.llm.provider_core.base import LLMProvider
    if isinstance(exc, ModelExecutionFailure):
        return dict(exc.details)
    chain=[]; current=exc
    while current is not None and len(chain)<6 and current not in chain:
        chain.append(current); current=current.__cause__ or current.__context__
    words=' '.join(str(item).lower() for item in chain)
    names=' '.join(type(item).__name__.lower() for item in chain)
    status=next((value for item in chain if (value:=LLMProvider._status_code_from_exception(item))),None)
    status=status or LLMProvider._status_code_from_message(words)
    if isinstance(exc,HTTPException): status=exc.status_code
    code,phase,retryable='model_execution_failed','model',False
    message='The model request did not complete. Retry once; if it persists, use the diagnostic reference.'
    if status in (401,403) or any(x in words for x in ('login expired','sign in','sign-in','authentication required')):
        status=status or 401; code='model_authentication_required'; phase='authentication'
        message='The selected model account needs authorization. Reconnect it in model settings.'
    elif any(x in words for x in ('certificate_verify_failed','tls certificate verification failed')) or 'sslcertverificationerror' in names:
        status=502;code='model_tls_failed';phase='connection'
        message='The model TLS certificate could not be verified. Check the system clock and trusted network or proxy certificate.'
    elif status==429 or any(x in words for x in ('usage quota exceeded','insufficient quota','insufficient balance','rate limit')):
        status=429;code='model_rate_or_quota_limit';phase='provider'
        message='The selected provider reports a rate or quota limit. Wait briefly or check that account quota.'
    elif status in (400,422):
        code='model_request_rejected';phase='request'
        message=f'The provider rejected the request (HTTP {status}). This can be a message or tool compatibility problem; reconnecting alone may not fix it.'
    elif status in (408,500,502,503,504) or any(x in names+' '+words for x in ('connecterror','connectionerror','connection failed','connection error','connection reset','transport request failed','remoteprotocolerror','connecttimeout','readtimeout','timed out','timeout','stream stalled')):
        status=status or 502;code='model_connection_interrupted';phase='connection';retryable=True
        message='The model connection was interrupted. Check the network or proxy and retry; the selected model has not been changed.'
    elif status==409:
        phase='configuration';message='The saved model selection changed or expired. Select the intended model again.'
    status=status or 502
    return {'code':code,'status':status,'phase':phase,'retryable':retryable,'message':message}


class ModelExecutionFailure(RuntimeError):
    def __init__(self,details):
        self.details=dict(details);self.status_code=details['status']
        super().__init__(details['message'])


async def invoke_with_recovery(call,*,on_content=None,on_reasoning=None,delays=(0.6,1.4)):
    """Never retry after content/reasoning is delivered, or after cancellation.

    The callback invokes inference only. Tools are returned to the caller and
    are never executed here. Provider-level retries must be disabled by caller.
    """
    delivered=False;trace=uuid.uuid4().hex[:16]
    async def content(value):
        nonlocal delivered
        if value:delivered=True
        if on_content:await on_content(value)
    async def reasoning(value):
        nonlocal delivered
        if value:delivered=True
        if on_reasoning:await on_reasoning(value)
    for attempt in range(len(delays)+1):
        try:
            response=await call(content,reasoning)
            if response.finish_reason=='error':
                raise RuntimeError(response.content or 'Model execution failed')
            return response
        except asyncio.CancelledError:raise
        except Exception as exc:
            details=failure_details(exc)
            details.update(trace_id=trace,attempts=attempt+1,partial_output=delivered)
            # No request text, endpoints, credentials or raw provider payloads.
            log.warning('Model failure trace=%s code=%s status=%s attempt=%s partial=%s',trace,details['code'],details['status'],attempt+1,delivered)
            if details['retryable'] and not delivered and attempt<len(delays):
                await asyncio.sleep(delays[attempt]);continue
            if delivered:
                details['message']+=' A partial response was retained; it was not automatically replayed.'
            raise ModelExecutionFailure(details) from exc

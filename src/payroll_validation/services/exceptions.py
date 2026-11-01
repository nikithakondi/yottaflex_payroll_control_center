"""Compatibility exports for exception management."""
from payroll_validation.services.exception_service import (list_exceptions, record_findings, assign_exception,
    review_exception, resolve_exception as _resolve_exception)


def resolve_exception(*args, **kwargs):
    """Accept the old repository adapter call and the DB-backed service call."""
    if len(args)>=4 and hasattr(args[0],"resolve"):
        repository,exception_id,resolution,actor=args[:4]
        return repository.resolve(exception_id,resolution=resolution,actor=actor)
    return _resolve_exception(*args,**kwargs)

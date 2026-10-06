from fastapi import Header, HTTPException


def get_current_org_id(x_org_id: str = Header(..., alias="X-Org-Id")) -> str:
    """
    Stand-in for real auth. In production this org_id comes off a verified
    JWT/session, never a client-supplied header — call that out explicitly
    if asked about it in the interview. It's stubbed as a header here so the
    tenant-isolation logic in the routers is easy to demo and test.
    """
    if not x_org_id:
        raise HTTPException(status_code=401, detail="Missing X-Org-Id")
    return x_org_id

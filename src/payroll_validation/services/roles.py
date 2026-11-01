"""Shared role and permission checks for payroll workflow services."""

ROLES = ("Employee", "Manager", "HR Partner", "IT/Operations Partner", "System Administrator")

def normalize_role(role):
    aliases = {"hr": "HR Partner", "payroll manager": "Manager", "approver": "Manager", "it": "IT/Operations Partner", "operations": "IT/Operations Partner", "admin": "System Administrator", "system administrator": "System Administrator", "it/operations partner": "IT/Operations Partner", "hr partner": "HR Partner", "manager": "Manager", "employee": "Employee"}
    try:
        return aliases[str(role).strip().lower()]
    except KeyError:
        raise ValueError(f"Unsupported reviewer role: {role}")

def require_role(role, allowed):
    role = normalize_role(role)
    if role not in allowed:
        raise PermissionError(f"Role {role} is not permitted to perform this action")
    return role

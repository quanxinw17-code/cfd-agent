class CFDAgentError(Exception):
    """Base error for CFD Agent failures."""


class GeometryError(CFDAgentError):
    pass


class MeshError(CFDAgentError):
    pass


class FluentSetupError(CFDAgentError):
    pass


class SolverError(CFDAgentError):
    pass


class PostprocessError(CFDAgentError):
    pass


class ReportError(CFDAgentError):
    pass


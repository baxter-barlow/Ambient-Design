"""Ground architecture, GA passes 1-4 (L2c, AMB-54): pass 3.

GA-1..GA-17 are normative by reference (spec 05/05), and ground analysis
is the prerequisite for the rest of T5 (GA Checker Notes section 1). Not
implemented yet: until L2c replaces this module, the pass supplies an
INTERIM GroundAnalysis that types a net as ground exactly when an author
labelled it with `ground_domain`, so the passes after it (ERC's ground
exemptions first) can be written against the final API. Its row says so,
and the driver records the pass as not implemented.
"""

NAME = "ground"
OWNER = "ground"
IMPLEMENTED = False


class GroundAnalysis:
    """Interim ground typing: a net is ground iff it carries an authored
    `ground_domain` label. L2c keeps the API and replaces the rule."""

    status = "interim"

    def __init__(self, model):
        self.ground_nets = tuple(name for name, net in model.nets.items()
                                 if net.ground_domain is not None)
        self._ground = frozenset(self.ground_nets)

    def is_ground(self, net: str) -> bool:
        return net in self._ground


def run(model, analysis, report):
    analysis.ground = GroundAnalysis(model)
    report.row("/", "interim", "ground-typing-from-labels",
               detail={"ground_nets": list(analysis.ground.ground_nets)})

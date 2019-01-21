"""
Queue backend abstraction manager.
"""

from .dask_adapter import DaskAdapter
from .fireworks_adapter import FireworksAdapter
from .parsl_adapter import ParslAdapter


def build_queue_adapter(workflow_client, logger=None, **kwargs):
    """Constructs a queue manager based off the incoming queue socket type.

    Parameters
    ----------
    workflow_client : object ("distributed.Client", "fireworks.LaunchPad")
        A object wrapper for different distributed workflow types
    logger : logging.Logger, Optional. Default: None
        Logger to report to
    **kwargs
        Additional kwargs for the Adapter

    Returns
    -------
    ret : Adapter
        Returns a valid Adapter for the selected computational queue
    """

    adapter_type = type(workflow_client).__module__ + "." + type(workflow_client).__name__

    if adapter_type == "parsl.config.Config":
        adapter = ParslAdapter(workflow_client, logger=logger)

    elif adapter_type == "distributed.client.Client":
        adapter = DaskAdapter(workflow_client, logger=logger)

    elif adapter_type == "fireworks.core.launchpad.LaunchPad":
        adapter = FireworksAdapter(workflow_client, logger=logger)

    else:
        raise KeyError("QueueAdapter type '{}' not understood".format(adapter_type))

    return adapter

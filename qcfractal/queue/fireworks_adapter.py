"""
Queue adapter for Fireworks
"""

import logging

from typing import Callable, Dict, List, Any, Optional

from .base_adapter import BaseAdapter


class FireworksAdapter(BaseAdapter):
    def __init__(self, client: Any, logger: Optional[logging.Logger]=None):
        BaseAdapter.__init__(self, client, logger)
        self.client.reset(None, require_password=False, max_reset_wo_password=int(1e8))

    def __repr__(self):
        return "<FireworksAdapter client=<LaunchPad host='{}' name='{}'>>".format(self.client.host, self.client.name)

    def submit_tasks(self, tasks: Dict[str, Any]) -> List[str]:
        ret = []

        import fireworks
        for task in tasks:
            tag = task["id"]

            fw = fireworks.Firework(
                fireworks.PyTask(
                    func=task["spec"]["function"],
                    args=task["spec"]["args"],
                    kwargs=task["spec"]["kwargs"],
                    stored_data_varname="fw_results"),
                spec={"_launch_dir": "/tmp/"})
            launches = self.client.add_wf(fw)

            self.queue[list(launches.values())[0]] = (tag, task["parser"], task["hooks"])
            ret.append(tag)

        return ret

    def acquire_complete(self) -> List[Dict[str, Any]]:
        ret = {}

        # Pull out completed results that match our queue ids
        cursor = self.client.launches.find({
            "fw_id": {
                "$in": list(self.queue.keys())
            },
            "state": {
                "$in": ["COMPLETED", "FIZZLED"]
            },
        }, {
            "action.stored_data.fw_results": True,
            "action.stored_data._task.args": True,
            "action.stored_data._exception": True,
            "_id": False,
            "fw_id": True,
            "state": True
        })

        for tmp_data in cursor:
            key, parser, hooks = self.queue.pop(tmp_data["fw_id"])
            if tmp_data["state"] == "COMPLETED":
                ret[key] = (tmp_data["action"]["stored_data"]["fw_results"], parser, hooks)
            else:
                blob = tmp_data["action"]["stored_data"]["_task"]["args"][0]
                msg = tmp_data["action"]["stored_data"]["_exception"]["_stacktrace"]
                blob["error_message"] = msg
                blob["success"] = False
                ret[key] = (blob, parser, hooks)

        return ret

    def await_results(self) -> bool:
        # Launch all results consecutively
        import fireworks.core.rocket_launcher
        fireworks.core.rocket_launcher.rapidfire(self.client, strm_lvl="CRITICAL")

    def close(self) -> bool:
        self.client.reset(None, require_password=False, max_reset_wo_password=int(1e8))
        return True
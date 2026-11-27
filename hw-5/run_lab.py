import argparse

from experiments.cluster import Cluster
from experiments.memory import MemoryExperiment
from experiments.parallel import ParallelCalculation
from experiments.scheduling import SchedulingExperiment
from experiments.storage import StorageMigration


def main():
    stages = {
        "memory": MemoryExperiment,
        "migrate": StorageMigration,
        "parallel": ParallelCalculation,
        "scheduling": SchedulingExperiment,
    }
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", *stages, "all"], default="all", nargs="?")
    arguments = parser.parse_args()
    cluster = Cluster()

    if arguments.stage in ("prepare", "all"):
        cluster.prepare()

    for name, experiment in stages.items():
        if arguments.stage in (name, "all"):
            print(f"Starting {name}", flush=True)
            experiment(cluster).run()
            print(f"Completed {name}", flush=True)


if __name__ == "__main__":
    main()

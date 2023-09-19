import os
import re
import networkx as nx
from pprint import pprint
import subprocess

# This is added for local test runs in checked out repo
if not os.getenv("GTIHUB_SHA"):
    os.environ["GITHUB_SHA"] = "HEAD"  # Use latest commit in local repo as the "pushed" commit.

# Use git diff-tree with flags to generate a list of the modified/added/removed files or folders.
cmd = subprocess.run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", str(os.getenv("GITHUB_SHA"))],
                     capture_output=True,
                     text=True,
                     check=True)

# Filter out changed paths that are not projects, or that are README.md files.
ign = re.compile("^(\\.github/.*|README\\.md|.*/README\\.md)$")
changed_projs_set = set()
for row in cmd.stdout.splitlines():
    if "/" in row and not re.fullmatch(ign, row):
        changed_projs_set.add(os.path.split(row)[0])

print("\nSet of changed projects:")
pprint(changed_projs_set)

# Read projects to ignore from file and add them to a set. This will automatically take care of duplicates.
ignore_file_path = ".deployignore"
if os.path.exists(ignore_file_path):
    with open(ignore_file_path, "r") as ignore_file:
        ignored_projs_set = set(ignore_file.read().splitlines())
    print("\nSet of ignored projects:")
    pprint(ignored_projs_set)

# Import dag from file in repo
graph = nx.DiGraph()
dagdata_path = "dag.txt"
with open(dagdata_path, 'r') as dagdata:
    graph.add_edges_from([tuple(row.split(" -> ")) for row in dagdata.read().strip().replace("\"", "").split(";")])

# Reverse direction of edges to get nodes in order of advisable deployment, since it is a dependency graph.
reverse_graph = graph.reverse()

# Remove all nodes that are ignored from the tree.
for node in ignored_projs_set:
    reverse_graph.remove_node(node)

projs_to_deploy = changed_projs_set - ignored_projs_set
for node in projs_to_deploy:
    projs_to_deploy = projs_to_deploy.union(set(nx.descendants(reverse_graph, node)))

# Remove all superfluous nodes from the graph.
for node in set(reverse_graph.nodes()):
    if node not in projs_to_deploy:
        reverse_graph.remove_node(node)

print("\nProjs to deploy:")
pprint(projs_to_deploy)

print("\nTopsorted reduced graph nodes together with their downstream neighbors:")
topsorted_reduced_graph_nodes = nx.topological_sort(reverse_graph)
pprint([(node, list(nx.neighbors(reverse_graph, node))) for node in topsorted_reduced_graph_nodes], width=150)
# Fill stages up with nodes of same generation, since they can be deployed in parallel. Begin with the first generation
# of the reduced reversed dependency graph. When out of stages, fill up the roundup stage with all remaining
# generations, in order of remaining generations, and execute all jobs in sequence (single file).
outputs = {
    "stage_one": {"project": []},
    "stage_two": {"project": []},
    "stage_three": {"project": []},
    "stage_four": {"project": []},
    "stage_five": {"project": []},
    "roundup": {"include": []}  # Want these to run in sequence due to possible multiple gens
}
stage_stack = list(reversed(list(outputs.keys())[:-1]))
for gen_members in nx.topological_generations(reverse_graph):
    if stage_stack:
        outputs[stage_stack.pop()]["project"].extend(gen_members)
    else:
        # If we are out of normal stages, fill up the round up with single file
        for member in gen_members:
            outputs["roundup"]["include"].append({"project": member})

# Print our results to job outputs
output_file = os.getenv("GITHUB_OUTPUT")

if output_file:
    with open(output_file, 'a') as f:
        for key, value in outputs.items():
            for inner_key, projlist in value.items():
                if projlist:
                    print(f"{key}={value}", file=f)
                else:
                    print(f"{key}=", file=f)
else:
    print("\nOutput matrix:")
    for key, value in outputs.items():
        for inner_key, projlist in value.items():
            if projlist:
                print(f"{key}={value}")
            else:
                print(f"{key}=")


# full_list = [('network', 0, 7, []),
#              ('vmimages', 0, 2, []),
#              ('databricks', 1, 5, ['network']),
#              ('datalake', 1, 6, ['network']),
#              ('vaults', 1, 6, ['network']),
#              ('logging', 3, 2, ['vaults', 'datalake', 'databricks']),
#              ('registry', 1, 3, ['network']),
#              ('aks', 2, 5, ['network', 'logging']),
#              ('devops', 4, 1, ['network', 'vaults', 'logging', 'vmimages']),
#              ('unity-catalog', 2, 0, ['databricks', 'datalake']),
#              ('gov-idc', 1, 0, ['datalake']),
#              ('gov-dadc', 5, 0, ['vaults', 'datalake', 'databricks', 'aks', 'registry']),
#              ('auth-ingest', 3, 0, ['aks', 'vaults', 'datalake']),
#              ('auth-devops', 7, 0, ['network', 'vaults', 'devops', 'aks', 'registry', 'databricks', 'vmimages']),
#              ('auth-aks', 2, 0, ['registry', 'aks']),
#              ('aks-deployments', 4, 0, ['aks', 'datalake', 'databricks', 'vaults'])]

from flask import Flask, request, render_template, redirect, url_for
from neo4j_library import Neo4jLibrary

app = Flask(__name__)
neo4j = Neo4jLibrary()


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Handle adding a node
        if "add_node" in request.form:
            label = request.form["node_label"]
            properties = {key: value for key, value in request.form.items() if key.startswith("node_property_")}
            query = neo4j.add_node(label, properties)  # Get the query string
            with neo4j.driver.session() as session:
                session.run(query, **properties)  # Execute the query
            return redirect(url_for("index"))

        # Handle adding an edge
        elif "add_edge" in request.form:
            node1_label = request.form["node1_label"]
            node1_key = request.form["node1_key"]
            node1_value = request.form["node1_value"]
            node2_label = request.form["node2_label"]
            node2_key = request.form["node2_key"]
            node2_value = request.form["node2_value"]
            edge_label = request.form["edge_label"]
            query = neo4j.add_edge(node1_label, node1_key, node1_value, node2_label, node2_key, node2_value, edge_label)
            with neo4j.driver.session() as session:
                session.run(query, node1_value=node1_value, node2_value=node2_value)  # Execute the query
            return redirect(url_for("index"))

    # Fetch nodes and edges to display on the web panel
    nodes = []
    edges = []
    with neo4j.driver.session() as session:
        # Fetch all nodes
        node_result = session.run("MATCH (n) RETURN id(n) as id, labels(n) as labels, properties(n) as props")
        for record in node_result:
            props = record["props"]
            display_label = list(props.values())[0] if props else str(record["id"])
            nodes.append({
                "id": record["id"],
                "label": f"{display_label} ({record['labels'][0] if record['labels'] else 'Node'})"
            })

        # Fetch all edges
        edge_result = session.run("MATCH (a)-[r]->(b) RETURN id(a) as source, id(b) as target, type(r) as type")
        for record in edge_result:
            edges.append({
                "from": record["source"],
                "to": record["target"],
                "label": record["type"]
            })

    return render_template("index.html", nodes=nodes, edges=edges)


if __name__ == "__main__":
    app.run(debug=False)
from flask import Flask, request, render_template, redirect, url_for
from neo4j import GraphDatabase
from dotenv import load_dotenv
import os

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

app = Flask(__name__)

driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def add_node(tx, label, properties):
    query = f"CREATE (n:{label} {{ {', '.join([f'{key}: ${key}' for key in properties.keys()])} }})"
    tx.run(query, **properties)


def add_edge(tx, node1_label, node1_key, node1_value, node2_label, node2_key, node2_value, edge_label):
    query = f"""
    MATCH (a:{node1_label} {{ {node1_key}: $node1_value }}), (b:{node2_label} {{ {node2_key}: $node2_value }})
    CREATE (a)-[:{edge_label}]->(b)
    """
    tx.run(query, node1_value=node1_value, node2_value=node2_value)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if "add_node" in request.form:
            label = request.form["node_label"]
            properties = {key: value for key, value in request.form.items() if key.startswith("node_property_")}
            with driver.session() as session:
                session.execute_write(add_node, label, properties)
            return redirect(url_for("index"))

        elif "add_edge" in request.form:
            node1_label = request.form["node1_label"]
            node1_key = request.form["node1_key"]
            node1_value = request.form["node1_value"]
            node2_label = request.form["node2_label"]
            node2_key = request.form["node2_key"]
            node2_value = request.form["node2_value"]
            edge_label = request.form["edge_label"]
            with driver.session() as session:
                session.execute_write(
                    add_edge, node1_label, node1_key, node1_value, node2_label, node2_key, node2_value, edge_label
                )
            return redirect(url_for("index"))

    nodes = []
    edges = []
    with driver.session() as session:
        node_result = session.run("MATCH (n) RETURN id(n) as id, labels(n) as labels, properties(n) as props")
        for record in node_result:
            props = record["props"]
            display_label = list(props.values())[0] if props else str(record["id"])
            nodes.append({
                "id": record["id"], 
                "label": f"{display_label} ({record['labels'][0] if record['labels'] else 'Node'})"
            })
        
        edge_result = session.run("MATCH (a)-[r]->(b) RETURN id(a) as source, id(b) as target, type(r) as type")
        for record in edge_result:
            edges.append({
                "from": record["source"], 
                "to": record["target"], 
                "label": record["type"]
            })

    return render_template("index.html", nodes=nodes, edges=edges)

if __name__ == "__main__":
    app.run(debug=True)
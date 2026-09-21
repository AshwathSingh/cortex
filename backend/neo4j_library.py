from neo4j import GraphDatabase
import os
import dotenv

dotenv.load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")


class Neo4jLibrary:
    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    # -------------------------------------
    #            SET FUNCTIONS
    # -------------------------------------

    def add_node(self, label, properties):
        query = f"CREATE (n:{label} {{ {', '.join([f'{key}: ${key}' for key in properties.keys()])} }})"
        return query

    def add_edge(self, node1_label, node1_key, node1_value, node2_label, node2_key, node2_value, edge_label):
        query = f"""
        MATCH (a:{node1_label} {{ '{node1_key}': $node1_value }}), (b:{node2_label} {{ '{node2_key}': $node2_value }})
        CREATE (a)-[:{edge_label}]->(b)
        """
        return query

    def delete_node(self, node_id):
        query = "MATCH (n) WHERE id(n) = $node_id DETACH DELETE n"
        return query

    def delete_edge(self, edge_id):
        query = "MATCH ()-[r]->() WHERE id(r) = $edge_id DELETE r"
        return query

    # -------------------------------------
    #           GET FUNCTIONS
    # -------------------------------------

    def get_properties(self, label):
        query = f"MATCH (n:{label}) RETURN properties(n) as props"
        return query

    def get_value(self, label, key):
        query = f"MATCH (n:{label}) RETURN n.{key} as value"
        return query

    def get_edges_of_node(self, node_id):
        query = """
        MATCH (n)-[r]->()
        WHERE id(n) = $node_id
        RETURN id(r) as edge_id, type(r) as edge_type, properties(r) as edge_props
        """
        return query

    def get_adjacent_nodes(self, node_id):
        query = """
        MATCH (n)-[]->(m)
        WHERE id(n) = $node_id
        RETURN id(m) as adjacent_node_id, labels(m) as adjacent_node_labels, properties(m) as adjacent_node_props
        """
        return query
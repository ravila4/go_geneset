import glob
import os

from biothings.utils.dataload import tabfile_feeder, dict_sweep, unlist
import mygene


def load_data(data_folder):
    # Ontology data
    go_file = os.path.join(data_folder, "go.obo")
    goterms = parse_obo(go_file)

    # Gene annotation files
    for f in glob.glob(os.path.join(data_folder, "*.gaf.gz")):
        docs = parse_gaf(f)

        # Join all gene sets and get NCBI IDs
        all_genes = set()
        for _id, annotations in docs.items():
            for key in ["genes", "excluded_genes", "contributing_genes",
                        "colocalized_genes"]:
                if annotations.get(key) is not None:
                    all_genes = all_genes | annotations[key]
        uniprot = [i for i, j in all_genes]
        symbols = [j for i, j in all_genes]
        taxid = annotations["taxid"]
        NCBI_dict = get_NCBI_id(symbols, uniprot, taxid)

        # Add additional annotations
        for _id, annotations in docs.items():
            # Add additional annotations
            annotations["go"] = {}
            annotations["go"]["id"] = _id
            annotations["go"]["name"] = goterms[_id]["name"]
            annotations["go"]["type"] = goterms[_id]["namespace"]
            annotations["go"]["description"] = goterms[_id]["def"]
            if annotations.get("genes") is not None:
                gene_dict = [{"uniprot": i, "symbol": j}
                             for i, j in annotations["genes"]]
                for d in gene_dict:
                    if NCBI_dict.get(d["symbol"]):
                        d["ncbigene"] = NCBI_dict.get(d["symbol"])
                    elif NCBI_dict.get(d["uniprot"]):
                        d["ncbigene"] = NCBI_dict.get(d["uniprot"])
                annotations["genes"] = gene_dict
            else:
                # No genes in set
                continue
            for key in ["excluded_genes", "contributing_genes",
                        "colocalized_genes"]:
                if annotations.get(key) is not None:
                    gene_dict = [{"uniprot": i, "symbol": j} for i, j in annotations[key]]
                    for d in gene_dict:
                        if NCBI_dict.get(d["symbol"]):
                            d["ncbigene"] = NCBI_dict.get(d["symbol"])
                        elif NCBI_dict.get(d["uniprot"]):
                            d["ncbigene"] = NCBI_dict.get(d["uniprot"])
                    annotations[key] = gene_dict
            # Clean up data
            annotations = dict_sweep(annotations)
            annotations = unlist(annotations)
            # Reorder keys
            annotations["_id"] = annotations["_id"] + "-" + annotations["taxid"]
            new_annotations = {}
            keys = ["_id", "date", "creator", "is_public", "taxid", "genes", "go"]
            for key in keys:
                new_annotations[key] = annotations[key]
            yield new_annotations


def get_NCBI_id(symbols, uniprot_ids, taxid):
    """Fetch NCBI id from gene symbols using mygene.info.
    If a gene symbol matches more than one NCBI id, all duplicate ids are kept.
    Gene symbols that are not found are retried using Uniprot ID.
    """
    mg = mygene.MyGeneInfo()
    response = mg.querymany(symbols, scopes='symbol', fields='entrezgene',
                            species=taxid, returnall=True)
    ncbi_ids = {}
    for out in response['out']:
        if out.get("entrezgene") is not None:
            query = out["query"]
            entrezgene = out["entrezgene"]
            ncbi_ids.setdefault(query, []).append(entrezgene)
    # Retry missing
    retry = [uniprot_ids[symbols.index(k)] for k in response["missing"]]
    response = mg.querymany(retry, scopes='uniprot', fields='entrezgene',
                            species=taxid, returnall=True)
    for out in response['out']:
        if out.get("entrezgene") is not None:
            query = out["query"]
            entrezgene = out["entrezgene"]
            ncbi_ids.setdefault(query, []).append(entrezgene)
    ncbi_ids = unlist(ncbi_ids)
    return ncbi_ids


def parse_gaf(f):
    """Parse a gene annotation (.gaf.gz) file."""
    data = tabfile_feeder(f, header=0)
    genesets = {}
    for rec in data:
        if not rec[0].startswith("!"):
            _id = rec[4]                    # Primary ID is GO ID
            if genesets.get(_id) is None:
                genesets[_id] = {}          # Dict to hold annotations
                genesets[_id]["_id"] = _id
                genesets[_id]["is_public"] = True
                genesets[_id]["taxid"] = rec[12].split("|")[0].replace(
                        "taxon:", "")
            uniprot = rec[1]
            symbol = rec[2]
            qualifiers = rec[3].split("|")
            # The gene can belong to several sets:
            if "NOT" in qualifiers:
                # Genes similar to genes in go term, but should be excluded
                genesets[_id].setdefault("excluded_genes", set()).add(
                        (uniprot, symbol))
            if "contributes_to" in qualifiers:
                # Genes that contribute to the specified go term
                genesets[_id].setdefault("contributing_genes", set()).add(
                        (uniprot, symbol))
            if "colocalizes_with" in qualifiers:
                # Genes colocalized with specified go term
                genesets[_id].setdefault("colocalized_genes", set()).add(
                        (uniprot, symbol))
            else:
                # Default list: genes that belong to go term
                genesets[_id].setdefault("genes", set()).add(
                        (uniprot, symbol))
    return genesets


def parse_obo(f):
    """Parse gene ontology (.obo) file.
    This file contains description and metadata for individual GO terms.
    Return a dictionary of GO term metadata with GO ids as keys.
    """
    go_terms = {}
    with open(f, 'r') as data:
        record = False  # True if line is part of a record (not a header)
        term_data = {}
        for line in data:
            line = line.replace("\n", "")
            # End of a record
            if line == "":
                if record:
                    _id = term_data['id']
                    go_terms[_id] = term_data
                    alt_id = term_data.get("alt_id")
                    if alt_id is not None:
                        # Add a duplicate entry with alt_id as key
                        go_terms[alt_id] = term_data
                record = False
            #  Line is part of a record
            if record:
                key, value = line.split(": ", 1)
                value = value.replace('"', '')
                if value.find("!") != -1:               # Remove comments
                    value = value.split(" ! ", 1)[0]
                term_data[key] = value               # Store key-value pair
            # Start of record
            if line.startswith("[Term]"):
                record = True
                term_data = {}
    return go_terms


if __name__ == "__main__":
    import json

    annotations = load_data("./test_data")
    for a in annotations:
        print(json.dumps(a, indent=2))
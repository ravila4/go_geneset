import glob
import json
import os

from biothings.utils.dataload import tabfile_feeder, dict_sweep, unlist
import mygene


def load_data(data_folder):
    # Ontology data
    go_file = os.path.join(data_folder, "go.json")
    goterms = parse_ontology(go_file)

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
        NCBI_dict = {} #get_NCBI_id(symbols, uniprot, taxid)

        # Add additional annotations
        for _id, annotations in docs.items():
            # Add additional annotations
            annotations["go"] = goterms[_id]
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
            annotations["_id"] = annotations["_id"] + "_" + annotations["taxid"]
            yield annotations


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
            query = out['query']
            entrezgene = out['entrezgene']
            ncbi_ids.setdefault(query, []).append(entrezgene)
    # Retry missing
    retry = [uniprot_ids[symbols.index(k)] for k in response['missing']]
    response = mg.querymany(retry, scopes='uniprot', fields='entrezgene',
                            species=taxid, returnall=True)
    for out in response['out']:
        if out.get("entrezgene") is not None:
            query = out['query']
            entrezgene = out['entrezgene']
            ncbi_ids.setdefault(query, []).append(entrezgene)
    ncbi_ids = unlist(ncbi_ids)
    return ncbi_ids


def parse_gaf(f):
    """Parse a gene annotation (.gaf.gz) file."""
    data = tabfile_feeder(f, header=0)
    genesets = {}
    for rec in data:
        if not rec[0].startswith("!"):
            _id = rec[4].replace(":", "_")  # Primary ID is GO ID
            if genesets.get(_id) is None:
                genesets[_id] = {}          # Dict to hold annotations
                genesets[_id]['_id'] = _id
                genesets[_id]['is_public'] = True
                genesets[_id]['taxid'] = rec[12].split("|")[0].replace(
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


def parse_ontology(f):
    with open(f, 'r') as infile:
        data = json.load(infile)
    nodes = data['graphs'][0]['nodes']
    go_terms = {}
    for node in nodes:
        url = node['id']
        _id = url.split("/")[-1]
        if not _id.startswith("GO_"):
            continue
        go_terms[_id] = {"id": _id.replace("_", ":"),
                         "url": url,
                         "name": node.get('lbl'),
                         "type": node.get('type'),
                         "definition": node['meta'].get("definition")}
    go_terms = unlist(go_terms)
    go_terms = dict_sweep(go_terms)
    return go_terms


if __name__ == "__main__":

    annotations = load_data("./test_data")
    for a in annotations:
        print(json.dumps(a, indent=2))

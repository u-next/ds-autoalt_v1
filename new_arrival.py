"""
3 logics to make new_arrival ALT

1). new EPs
* POC@new_arrival-new_ep.ipynb
* new_ep_recommender()

2). new SIDs
two approaches
* based on User Similarity
* based on Tag Similarity

3). popular new SIDs -> different implementation, do it later


=> mix 1, 2, 3 together


"""

import pandas as pd
import numpy as np
import pickle
import os, sys, tempfile, logging, time
import numpy as np
import time
import csv
import operator
from pathlib import Path
from implicit.bpr import BayesianPersonalizedRanking
from recoalgos.matrixfactor.bpr import BPRRecommender
from scipy.sparse import coo_matrix
from dstools.logging import setup_logging
from dstools.utils import normalize_path, save_list_to_file, file_to_list


logger = logging.getLogger(__name__)

# TODO: move to tool.py
def load_model(path):
    return pickle.load(open(path, "rb"))

def batch(iterable, n=1):
    l = len(iterable)
    for ndx in range(0, l, n):
        yield iterable[ndx:min(ndx + n, l)]


def rerank_seen(model,
                target_users=None,
                target_items=None,
                batch_size=500):
    """
    rank seens SIDs and return

    :param target_users: UID list, [uid1, uid2, ...]; None means all users in matrix
    :param target_items: SID list  [sid1, sid2, ...]; None means all items in matrix
    :param filter_already_liked_items: removed the nonzeros item in matrix, set False if you have special filtering
    :param N: minimum nb of output
    :param batch_size:
    :yield: uid, sid list
    """

    # user id -> matrix index
    if target_users is None:
        target_users_index_list = list(model.user_item_matrix.user2id.values())  # TODO [:10] is for testing
    else:
        target_users_index_list = [model.user_item_matrix.user2id.get(user) for user in target_users if
                                   model.user_item_matrix.user2id.get(user) is not None]

    # make target matrix, which contains target items only
    if target_items is None:
        # SID -> matrix index
        target_items2actualid = {i: i for i in range(model.user_item_matrix.matrix.shape[1])}
        target_matrix = model.user_item_matrix.matrix
        item_factors = model.item_factors
    else:
        target_items_index_list = list({model.user_item_matrix.item2id.get(item) for item in target_items if
                                        model.user_item_matrix.item2id.get(item) is not None})
        # matrix_index -> target_matrix_index
        target_items2actualid = {i: target for i, target in enumerate(target_items_index_list)}
        # target_matrix[nb of user, nb of target items], contains target items only by target_matrix_index
        target_matrix = model.user_item_matrix.matrix[:, target_items_index_list]
        item_factors = model.item_factors[target_items_index_list, :]

    # matrix operation on batch of user
    for uidxs in batch(target_users_index_list, batch_size):

        # for uidxs(a batch of user), get the score for target items,
        scores = model.user_factors[uidxs].dot(item_factors.T)
        rows = target_matrix[uidxs]

        for i, uid in enumerate(uidxs):  # for each user
            nonzeros_in_row = set(rows[i].nonzero()[1])
            best = sorted(enumerate(scores[i]), key=lambda x: -x[1])

            # only keep nonzero indice == already seen items
            reranked_targer_items = [(index, score) for index, score in best if index in nonzeros_in_row]
            score_list = [score for index, score in reranked_targer_items]
            # target matrix index -> matrix index -> item id
            reranked_item_indexs = [model.user_item_matrix.id2item[target_items2actualid[index]]
                                    for index, score in reranked_targer_items]

            yield model.user_item_matrix.id2user[uid], reranked_item_indexs, score_list


def new_arrival_loader(input_path="data/new_arrival_EP_7_days.csv"):
    """
    :return: dict {sakuhin_public_code:episode_public_code}
    """
    eps = pd.read_csv(input_path)
    # dataframe already ordered by episode_no -> keep the most front ep
    eps = eps[~ eps.duplicated(subset='sakuhin_public_code', keep='first')]
    return {sid: epc for sid, epc in zip(eps['sakuhin_public_code'], eps['episode_public_code'])}


# past N days is corresponding to past N days of new_arrival_EP.csv
def user_session_reader(input_path="data/new_user_sessions_7_days.csv"):
    """
    input format:
    "user_id", "SIDs..." , "episode_public_codes...", "watch times"

    :return: a dict {user_id: { SID: episode_public_codes}}
    """
    us_dict = {}
    with open(input_path, "r") as r:
        r.readline()
        while True:
            line = r.readline()
            if line:
                arr = line.rstrip().replace('"', '').split(",")
                nb = len(arr) - 1
                SIDs = arr[1:1 + int(nb / 3)]
                EPs = arr[1 + int(nb / 3):1 + int(nb / 3) * 2]
                us_dict.setdefault(arr[0], {k:v for k, v in zip(SIDs, EPs)})
            else:
                break
    return us_dict


def new_ep_recommender(model_path):
    """
    1004025 users are binge-watching sth
    took 35623.121743917465  ~= 10 hrs

    :return: a dict {user_id:[SIDs with new ep]}
    """
    model = load_model(model_path)
    new_arrival_sid_epc = new_arrival_loader()
    user_session = user_session_reader()

    new_ep_reco = {}

    for uid, sid_list, score_list in rerank_seen(model, None, None, True):
        # get new EPs of user binge-watching sakuhins
        user_interesting_new_eps = [(sid, new_arrival_sid_epc.get(sid)) for sid in sid_list if
                                    new_arrival_sid_epc.get(sid, False)]
        if user_interesting_new_eps:

            # remove already watched EP
            watched_eps = user_session.get(uid, None)
            if watched_eps:
                watched_eps = set(watched_eps)
                new_ep_reco.setdefault(uid, [sid for sid, ep in user_interesting_new_eps if ep not in watched_eps])
            else:
                new_ep_reco.setdefault(uid, [sid for sid, ep in user_interesting_new_eps])

    logging.info(f"{len(new_ep_reco)} users are binge-watching sth")
    # TODO: same series reco

    # TODO: update N past days daily or just one day daily?

    return new_ep_reco


def reco_by_user_similarity(model_path,
                            nb_similar_user=10000,
                            new_arrival_SIDs_path="data/new_arrival_SID_7_days.csv",
                            new_user_session_path="data/new_user_sessions_7_days.csv"):
    """
    nb_similar_user=10000
    142 new arrival SIDs -> 110 done / 32 sakuhins haven't been watched yet
    user coverage rate: 1767708/1900365 = 0.93
    took 185s ~= 6m

    :return: new_sid_reco {'PM023203146': {'SIDs': ['SID0048896',...], 'scores': [2.183024, ...]} }
    """
    logging.info("running reco_by_user_similarity")

    model = load_model(model_path)

    id2user = {}
    for user, id_ in model.user_item_matrix.user2id.items():
        id2user[id_] = user

    # read new arrival SIDs as dict( SID: [])
    new_arrival_SIDs = {}
    with open(new_arrival_SIDs_path, "r") as r:
        r.readline()
        for line in r.readlines():
            new_arrival_SIDs.setdefault(line.rstrip().replace('"', ''), [])
    logging.info(f"{len(new_arrival_SIDs)} new arrival SIDs ")

    # user sessions for new arrival SIDs
    with open(new_user_session_path, "r") as r:
        r.readline()
        while True:
            line = r.readline()
            if line:
                arr = line.rstrip().replace('"', '').split(",")
                nb = len(arr) - 1
                SIDs = arr[1:1 + int(nb / 3)]
                for SID in SIDs:
                    user_id_list = new_arrival_SIDs.get(SID, None)
                    if user_id_list != None and arr[0] not in user_id_list:
                        new_arrival_SIDs[SID] = user_id_list + [arr[0]]
            else:
                break

    # make reco
    new_sid_reco = {}
    nb_nobody_wacth_sid = 0
    for SID, watched_user_list in new_arrival_SIDs.items():
        if not watched_user_list:
            nb_nobody_wacth_sid += 1
            continue

        similar_users = {}  # user_index: similarity score
        for user_id in watched_user_list:
            u_index = model.user_item_matrix.user2id.get(user_id, None)
            if u_index:
                # TODO: use the largest socre
                similar_users.update({index: score for (index, score) in model.bpr_model.similar_users(u_index, nb_similar_user)})

        # 186132: 2.8023417  ->  PM017329518:[ [SID0048732], [2.8023417] ]
        for user_index, score in similar_users.items():
            user_id = id2user[user_index]
            tmp = new_sid_reco.setdefault(user_id, {'SIDs':[], 'scores':[]})
            tmp['SIDs'] = tmp['SIDs'] + [SID]
            tmp['scores'] = tmp['scores'] + [score]
            new_sid_reco[user_id] = tmp

    logging.info(f" {len(new_arrival_SIDs) - nb_nobody_wacth_sid} done / {nb_nobody_wacth_sid} sakuhins haven't been watched yet")
    logging.info(f"user coverage rate: {len(new_sid_reco)}/{len(model.user_item_matrix.user2id)} = "
                 f"{float(len(new_sid_reco))/len(model.user_item_matrix.user2id)}")
    return new_sid_reco


def make_alt(model_path, alt_public_code="ALT_new_arrival", alt_domain="SOUGOU"):
    logging.info(f"making {alt_public_code} on {alt_domain} using model:{model_path}")

    #start_time = time.time()
    # new_ep_reco = new_ep_recommender(model_path)
    #logging.info(f"took {time.time() - start_time}")

    # user-similarity
    start_time = time.time()
    new_sid_reco = reco_by_user_similarity(model_path)
    logging.info(f"took {time.time() - start_time}")
    # user preference
    with open("new_arrival_reco.csv", "w") as w:
        for user_id, sid_scores in new_sid_reco.items():
            # TODO: rank SIDs by score
            w.write(f"{user_id},{sid_scores['SIDs']},{sid_scores['scores']}\n")

    # popularity




if __name__ == '__main__':
    pass



































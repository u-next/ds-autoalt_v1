"""
3 logics to make new_arrival ALT

1). new EPs
* POC@new_arrival-new_ep.ipynb
* new_ep_recommender()

2). new SIDs
two approaches
* based on User Similarity
* based on Tag Similarity

3). popular new SIDs -> different implementation, future project


=> mix 1, 2, 3 together


"""

import pandas as pd
import logging
import time
import operator
from autoalts.autoalt_maker import AutoAltMaker
from autoalts.utils import efficient_reading

logging.basicConfig(level=logging.INFO)


class NewArrival(AutoAltMaker):
    def __init__(self, **kwargs):
        super().__init__(alt_info=kwargs["alt_info"], create_date=kwargs["create_date"], blacklist_path=kwargs["blacklist_path"],
                         series_path=kwargs["series_path"], max_nb_reco=kwargs["max_nb_reco"], min_nb_reco=kwargs["min_nb_reco"])
        self.target_users = None
        if kwargs['target_users_path']:
            self.target_users = self.read_target_users(kwargs['target_users_path'])

    def make_alt(self, **kwargs):
        logging.info(f"making {self.alt_info} using model:{kwargs['bpr_model_path']}")
        if self.alt_info['domain'].values[0] == "ippan_sakuhin":
            self.new_ep_recommender(**kwargs)
        elif self.alt_info['domain'].values[0] == "semiadult":
            self.semi_adult(kwargs['input_path'])
        elif self.alt_info['domain'].values[0] == "book":
            raise Exception("Not implemented yet")
        else:
            raise Exception(f"unknown ALT_domain:{self.alt_info['domain'].values[0]}")

    def semi_adult(self, input_path):
        """
        logic: for semi_adult, only new SID, no new EPs
        MVP: same new arrival for everyone -> TODO: seredipity
        :return:
        """
        new_SIDs = []
        with open(input_path,"r") as r:
            r.readline()
            for line in r.readlines():
                new_SID = line.rstrip().replace('"', '')
                if new_SID not in new_SIDs:
                    new_SIDs.append(new_SID)

        if len(new_SIDs) == 0:
            raise Exception("[ERROR] input: {input_path} has no data")

        reco_str = '|'.join(new_SIDs[:self.max_nb_reco])

        with open(f"{self.alt_info['feature_public_code'].values[0]}.csv", "w") as w:
            w.write(self.config['header']['feature_table'])
            w.write(f"COMMON,{self.alt_info['feature_public_code'].values[0]},{self.create_date},{reco_str},"
                    f"{self.alt_info['feature_title'].values[0]},{self.alt_info['domain'].values[0]},1,"
                    f"{self.config['feature_public_start_datetime']},{self.config['feature_public_end_datetime']}\n")

    def new_ep_recommender(self, **kwargs):
        """
        669933 users are binge-watching sth,
        took 494s

        :return: a dict {user_id:{SIDA:scoreA, SIDB:scoreB, ...}
        """
        model = self.load_model(kwargs['bpr_model_path'])
        new_arrival_sid_epc = self.new_arrival_ep_loader(kwargs['new_arrival_EP_path'])  # {sakuhin_public_code:episode_public_code}
        user_watched_EPs = self.user_ep_reader(kwargs['user_ep_history_path'])  # { user_id: [watched EPs] }

        logging.info(f"{len(new_arrival_sid_epc)} SIDs w/ new arrival EP")

        nb_all_users = 0
        nb_new_arrival_users = 0

        with open(f"{self.alt_info['feature_public_code'].values[0]}.csv", "w") as w:
            w.write(self.config['header']['feature_table'])
            for userid, sid_list, score_list in self.rerank_seen(model, target_users=self.target_users,
                                                                 target_items=list(new_arrival_sid_epc.keys()),
                                                                 batch_size=10000):
                nb_all_users += 1
                if nb_all_users % 50000 == 0:
                    logging.info('progress: {:.3f}%'.format(float(nb_all_users) / len(model.user_item_matrix.user2id) * 100))

                # get new EPs of user binge-watching sakuhins
                user_interesting_new_eps = [(sid, new_arrival_sid_epc.get(sid)) for sid in sid_list if new_arrival_sid_epc.get(sid, None)]

                if len(user_interesting_new_eps) < self.min_nb_reco:
                    continue

                if user_interesting_new_eps:
                    watched_eps = user_watched_EPs.get(userid, None)

                    if watched_eps:  # remove already watched EP
                        watched_eps = set(watched_eps)
                        reco = [sid for (sid, ep) in user_interesting_new_eps if ep not in watched_eps]
                    else:
                        reco = [sid for (sid, ep) in user_interesting_new_eps]

                    # reco = self.black_list_filtering(reco)  # unnecessary, since this SID is what user interested
                    if self.series_dict:
                        reco = self.rm_series(reco)

                    if len(reco) < self.min_nb_reco:
                        continue

                    w.write(
                        f"{userid},{self.alt_info['feature_public_code'].values[0]},{self.create_date},{'|'.join(reco)},"
                        f"{self.alt_info['feature_title'].values[0]},{self.alt_info['domain'].values[0]},1,"
                        f"{self.config['feature_public_start_datetime']},{self.config['feature_public_end_datetime']}\n")
                    nb_new_arrival_users += 1

        logging.info("{} users got reco / total nb of user: {}, coverage rate={:.3f}%".format(nb_new_arrival_users, nb_all_users,
                                                                                             nb_new_arrival_users / nb_all_users*100))

    def rerank_seen(self, model,
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
        if not target_users:
            target_users_index_list = list(model.user_item_matrix.user2id.values())
        else:
            target_users_index_list = [model.user_item_matrix.user2id.get(user) for user in target_users if
                                       model.user_item_matrix.user2id.get(user, None)]

        # make target matrix, which contains target items only
        if not target_items:
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

        logging.info(f"do seen SID ranking for {len(target_users_index_list)} target users")
        logging.info(f"do seen SID ranking for {len(item_factors)} target items")

        # matrix operation on batch of user
        for uidxs in self.batch(target_users_index_list, batch_size):

            # for uidxs(a batch of user), get the score for target items,
            scores = model.user_factors[uidxs].dot(item_factors.T)
            rows = target_matrix[uidxs]

            for i, uid in enumerate(uidxs):  # for each user
                nonzeros_in_row = set(rows[i].nonzero()[1])
                best = sorted(enumerate(scores[i]), key=lambda x: -x[1])

                # only keep nonzero indices == already seen items
                reranked_targer_items = [(index, score) for index, score in best if index in nonzeros_in_row]
                score_list = [score for index, score in reranked_targer_items]
                # target matrix index -> matrix index -> item id
                reranked_item_indexs = [model.user_item_matrix.id2item[target_items2actualid[index]]
                                        for index, score in reranked_targer_items]

                yield model.user_item_matrix.id2user[uid], reranked_item_indexs, score_list

    def new_arrival_ep_loader(self, input_path="data/new_arrival_EP.csv"):
        """
        :return: dict {sakuhin_public_code:episode_public_code}
        """
        eps = pd.read_csv(input_path)
        # dataframe already ordered by episode_no -> keep the most front ep
        eps = eps[~ eps.duplicated(subset='sakuhin_public_code', keep='first')]
        return {sid: epc for sid, epc in zip(eps['sakuhin_public_code'], eps['episode_public_code'])}

    def user_ep_reader(self, input="data/user_ep_history.csv"):
        user_watched_EPs = {}  # { user_id: [EPs] }

        for line in efficient_reading(input):
            arr = line.rstrip().split(",")
            user_watched_EPs[arr[0]] = arr[1].split("|")
        return user_watched_EPs

    # past N days is corresponding to past N days of new_arrival_EP.csv
    def user_session_reader(self, input_path="data/new_user_sessions.csv"):
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
                    us_dict.setdefault(arr[0], {k: v for k, v in zip(SIDs, EPs)})
                else:
                    break
        return us_dict

    def video_domain(self, alt_info, create_date, model_path, output_name):
        """
        not get used by far,
        :param create_date:
        :param model_path:
        :param output_name:
        :return:
        """
        start_time = time.time()

        new_arrival_ep_reco = self.new_ep_recommender(model_path)
        logging.info(f"took {time.time() - start_time}")

        logging.info("merge & rank by score")
        with open(output_name, "w") as w:  # TODO: new_arrival_reco
            w.write("user_multi_account_id,feature_public_code,create_date,sakuhin_codes,"
                    "feature_title,feature_description,domain,autoalt\n")
            for userid in new_arrival_ep_reco.keys():
                # combine recommendations
                sid_score_dict = {}
                sid_score_dict.update(new_arrival_ep_reco.get(userid, {}))
                sid_list, score_list = [], []
                for k, v in sorted(sid_score_dict.items(), key=operator.itemgetter(1), reverse=True):
                    sid_list.append(k)
                    score_list.append('{:.3f}'.format(v))
                # w.write(f'{user_id},{"|".join(sid_list)},1.0\n')
                w.write(f"{userid},{alt_info['feature_public_code'].values[0]},{create_date},{'|'.join(sid_list)},"
                        f"{alt_info['feature_title'].values[0]},,{alt_info['domain'].values[0]},1\n")

        """
        # user-similarity  TODO: replaced by serendipity
        start_time = time.time()
        new_arrival_sid_reco, nb_nobody_wacthed_sids = reco_by_user_similarity(model_path)
        logging.info(f"took {time.time() - start_time}")

        logging.info("merge & rank by score")
        with open(output_name, "w") as w:  # TODO: new_arrival_reco
            for user_id in (set(new_arrival_ep_reco.keys()) | set(new_arrival_sid_reco.keys())):
                # combine recommendations
                sid_score_dict = {}
                sid_score_dict.update(new_arrival_ep_reco.get(user_id, {}))
                sid_score_dict.update(new_arrival_sid_reco.get(user_id, {}))
                sid_list, score_list = [], []
                for k,v in sorted(sid_score_dict.items(), key=operator.itemgetter(1), reverse=True):
                    sid_list.append(k)
                    score_list.append('{:.3f}'.format(v))
                w.write(f'{user_id},{"|".join(sid_list)},1.0\n')
        """

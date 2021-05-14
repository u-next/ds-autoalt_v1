import logging
from autoalts.autoalt_maker import AutoAltMaker
from utils import efficient_reading

logging.basicConfig(level=logging.INFO)


class BecauseYouWatched(AutoAltMaker):
    def __init__(self, alt_info, create_date, blacklist_path, sid_name_path, target_users_path=None, series_path=None, max_nb_reco=30, min_nb_reco=2):
        super().__init__(alt_info, create_date, blacklist_path, series_path, max_nb_reco, min_nb_reco)
        self.sid_name_dict = self.read_sid_name(sid_name_path)
        self.target_users = None
        if target_users_path:
            self.target_users = self.read_target_users(target_users_path)
            self.target_users = set(self.target_users)

    def make_alt(self, watched_list=None):
        if self.alt_info['domain'].values[0] == "ippan_sakuhin":
            self.video_byw(user_sid_history_path=watched_list)
        elif self.alt_info['domain'].values[0] == "semiadult":
            self.semiadult(user_sid_history_path=watched_list)
        elif self.alt_info['domain'].values[0] == "book":
            raise Exception("Not implemented yet")
        else:
            raise Exception(f"unknown ALT_domain:{self.alt_info['domain'].values[0]}")

    # past N days is corresponding to past N days of new_arrival_EP.csv
    def new_user_session_reader(self, input_path="data/new_user_sessions.csv"):
        """
        input format:
        "user_id", "SIDs..." , "episode_public_codes...", "watch times"

        :return: a dict {user_id: { SID: episode_public_codes}}
        """
        with open(input_path, "r") as r:
            r.readline()
            while True:
                line = r.readline()
                if line:
                    arr = line.rstrip().replace('"', '').split(",")
                    if arr[0] == '':  # userid == '' represent users w/o login
                        continue
                    nb = len(arr) - 1
                    SIDs = arr[1:1 + int(nb / 3)]
                    yield arr[0], list(set(SIDs))
                else:
                    break

    def read_sid_name(self, sid_name_path):
        logging.info("loading sid, name lookup table")
        sid_name_dict = {}
        with open(sid_name_path, "r") as r:
            r.readline()
            while True:
                line = r.readline()
                if line:
                    arr = line.rstrip().split(",")
                    sid_name_dict.setdefault(arr[0], " ".join(arr[1:]))  # remove , in title to prevent bugs
                else:
                    break
        return sid_name_dict

    def semiadult(self, user_sid_history_path,
                  postplay_path="data/postplay_semiadult_implicit.csv"):
        """
        logic: due to lack of data and 作品, don't use watched_list to filter out watched SIDs
        """
        logging.info("loading postplay as ICF reco")
        icf_dict = {}
        for line in efficient_reading(postplay_path, with_header=False):
            arrs = line.rstrip().split(",")
            icf_dict.setdefault(arrs[0], arrs[1].split("|"))
        logging.info(f"cbf table has {len(icf_dict)} items")

        nb_all_users = 0
        nb_byw_users = 0

        logging.info("making because_you_watched rows for new session users")
        with open(f"{self.alt_info['feature_public_code'].values[0]}.csv", "w") as w:
            w.write(self.config['header']['feature_table'])

            for line in efficient_reading(user_sid_history_path):
                arr = line.rstrip().split(",")  # user_multi_account_id,sids
                userid = arr[0]

                if self.target_users and userid not in self.target_users:
                    continue

                nb_all_users += 1
                if nb_all_users % 10000 == 0:
                    logging.info(f"Now processing No.{nb_all_users} user")

                watched_SIDs = arr[1].split("|")

                for watched_SID in watched_SIDs:
                    cbf_reco = icf_dict.get(watched_SID, None)

                    if cbf_reco and len(cbf_reco) >= self.min_nb_reco:
                        title = self.sid_name_dict.get(watched_SID, None)
                        if title:
                            title = title.rstrip().replace('"', '').replace("'", "")
                            title = self.alt_info['feature_title'].values[0].replace("○○", title)
                            w.write(f"{userid},{self.alt_info['feature_public_code'].values[0]},{self.create_date},{'|'.join(cbf_reco)},"
                                    f"{title},{self.alt_info['domain'].values[0]},1,"
                                    f"{self.config['feature_public_start_datetime']},{self.config['feature_public_end_datetime']}\n")
                            nb_byw_users += 1
                            # TODO: for MVP, we only make one BYW FET for one user
                            break
                        else:
                            logging.warning(f"{watched_SID} can not find a mapping title")
                    else:
                        continue
        logging.info(
            "{} users got reco / total nb of user: {}, coverage rate={:.3f}".format(nb_byw_users, nb_all_users,
                                                                                    nb_byw_users / nb_all_users))


    def semiadult_v1(self, user_sessions_path='data/new_user_sessions.csv',
                  postplay_path="data/semiadult_postplay_implicit.csv",
                  sid_name_path="data/sid_name_dict.csv"):
        """
        logic: due to lack of data and 作品, don't use watched_list to filter out watched SIDs
        """
        logging.info("loading postplay as ICF reco")
        icf_dict = {}
        with open(postplay_path, 'r') as r:  # SID, SID|SID|...
            while True:
                line = r.readline()
                if line:
                    arrs = line.rstrip().split(",")
                    cbf_recos = icf_dict.get(arrs[0], None)
                    if cbf_recos:
                        cbf_recos = cbf_recos.split("|")
                        postplay_recos = [sid for sid in arrs[1].split("|") if sid not in cbf_recos]
                        icf_dict[arrs[0]] = '|'.join(cbf_recos + postplay_recos)
                    else:
                        icf_dict.setdefault(arrs[0], arrs[1])
                else:
                    break
        logging.info(f"cbf table has {len(icf_dict)} items")

        logging.info("making because_you_watched rows for new session users")
        with open(f"{self.alt_info['feature_public_code'].values[0]}.csv", "w") as w:
            w.write(self.config['header']['autoalt'])
            line_counter = 0
            for (userid, session_sids) in self.new_user_session_reader(input_path=user_sessions_path):
                line_counter += 1

                # check the similarity between cbf_rs_lists of SIDs
                # to record which session_sids are alive after removing similar SIDs.  SIDs:session_id
                session_dict = {icf_dict[session_sid]: session_sid for session_sid in session_sids if
                                icf_dict.get(session_sid, None)}
                cbf_rs_lists = [k.split("|") for k, v in session_dict.items()]
                similar_threshold = 0.5
                to_del = []

                while True:
                    if len(cbf_rs_lists) <= 1:
                        break

                    for i in range(len(cbf_rs_lists) - 1):
                        for j in range(i + 1, len(cbf_rs_lists)):
                            sa = set(cbf_rs_lists[i])
                            sb = set(cbf_rs_lists[j])
                            if max(len(sa & sb) / len(sa), len(sa & sb) / len(sb)) > similar_threshold:
                                to_del.append(cbf_rs_lists[j])
                        if to_del:
                            break
                    else:
                        break

                    if to_del:
                        for e in to_del:
                            cbf_rs_lists.remove(e)
                            del session_dict["|".join(e)]
                        to_del = []

                for SIDs, session_SID in session_dict.items():
                    # blacklist filtering & watched SID filtering
                    arrs = [sid for sid in SIDs.split("|")]

                    # TODO: current order of SIDs is based on cbf scores, we can mix cbf score with user bpr score
                    if len(arrs) >= self.min_nb_reco:
                        title = self.sid_name_dict.get(session_SID, None)
                        if title:
                            title = title.rstrip().replace('"', '').replace("'", "")
                            title = self.alt_info['feature_title'].values[0].replace("○○", title)

                            w.write(f"{userid},{self.alt_info['feature_public_code'].values[0]},{self.create_date},{'|'.join(arrs)},"
                                    f"{title},{self.alt_info['domain'].values[0]},1\n")

                            # TODO: for MVP, we only make one BYW FET
                            break
                        else:
                            logging.warning(f"{session_SID} can not find a mapping title")
                else:
                    pass
            logging.info(f"{line_counter} lines processed")

    def video_byw(self, user_sid_history_path,
                  cbf_table_path="data/cbf_rs_list.csv",
                  postplay_path="data/postplay_implicit.csv"):
        """
        video-video similarity for because you watched(BYW)

        current logic:
        get all SIDs from user watch history
        ->  remove SIDs whose cbf_list is similar to others

        output: one line for one byw_sid, user may have several lines for each SID he watched
        user_multi_account_id,byw_sid,sakuhin_codes,alt_score
        user_multi_account_id,byw_sid,sakuhin_codes,alt_score


        :param cbf_table_path: sakuhin_public_code, rs_list
        """
        # TODO: rerank by BPR, currrent workaround = no reranking <- may need A/B test
        # TODO: daily update version

        logging.info("loading content-based filtering recommendation")
        cbf_dict = {}
        with open(cbf_table_path, 'r') as r:  # SID, SID|SID|...
            while True:
                line = r.readline()
                if line:
                    arrs = line.rstrip().split(",")
                    cbf_dict.setdefault(arrs[0], arrs[1])
                else:
                    break

        logging.info("loading postplay to complement cbf")
        with open(postplay_path, 'r') as r:  # SID, SID|SID|...
            while True:
                line = r.readline()
                if line:
                    arrs = line.rstrip().split(",")
                    cbf_recos = cbf_dict.get(arrs[0], None)
                    if cbf_recos:
                        cbf_recos = cbf_recos.split("|")
                        postplay_recos = [sid for sid in arrs[1].split("|") if sid not in cbf_recos]
                        cbf_dict[arrs[0]] = '|'.join(cbf_recos+postplay_recos)
                    else:
                        cbf_dict.setdefault(arrs[0], arrs[1])
                else:
                    break
        logging.info(f"cbf table has {len(cbf_dict)} items")

        nb_all_users = 0
        nb_byw_users = 0

        logging.info("making because_you_watched rows for new session users")
        with open(f"{self.alt_info['feature_public_code'].values[0]}.csv", "w") as w:
            w.write(self.config['header']['feature_table'])

            for line in efficient_reading(user_sid_history_path):
                arr = line.rstrip().split(",")  # user_multi_account_id,sids
                userid = arr[0]

                if self.target_users and userid not in self.target_users:
                    continue

                nb_all_users += 1
                if nb_all_users % 10000 == 0:
                    logging.info(f"Now processing No.{nb_all_users} user")

                watched_SIDs = arr[1].split("|")

                for watched_SID in watched_SIDs:
                    if watched_SID in self.blacklist:  # only make reco for not black list SID
                        continue

                    cbf_reco = cbf_dict.get(watched_SID, None)
                    ban_list = self.blacklist | set(watched_SIDs)

                    if cbf_reco:
                        cbf_reco = [sid for sid in cbf_reco.split("|") if sid not in ban_list]  # cbf = SID|SID|...

                        # also remove same series SIDs of watched_SID; don't want to reco S2 if watched_SID is S3
                        cbf_reco = self.rm_series([watched_SID] + cbf_reco)[1:]

                        if len(cbf_reco) >= self.min_nb_reco:
                            title = self.sid_name_dict.get(watched_SID, None)
                            if title:
                                title = title.rstrip().replace('"', '').replace("'", "")
                                title = self.alt_info['feature_title'].values[0].replace("○○", title)

                                w.write(f"{userid},{self.alt_info['feature_public_code'].values[0]},{self.create_date},{'|'.join(cbf_reco)},"
                                        f"{title},{self.alt_info['domain'].values[0]},1,"
                                        f"{self.config['feature_public_start_datetime']},{self.config['feature_public_end_datetime']}\n")
                                nb_byw_users += 1
                                # TODO: for MVP, we only make one BYW FET for one user
                                break
                            else:
                                logging.warning(f"{watched_SID} can not find a mapping title")
                    else:
                        continue
        logging.info("{} users got reco / total nb of user: {}, coverage rate={:.3f}".format(nb_byw_users, nb_all_users,
                                                                                             nb_byw_users/nb_all_users))


    def video_byw_v1(self, watched_list_ippan=None,
                  user_sessions_path='data/new_user_sessions.csv',
                  cbf_table_path="data/cbf_rs_list.csv",
                  postplay_path="data/postplay_implicit.csv",
                  sid_name_path="data/sid_name_dict.csv"):
        """
        video-video similarity for because you watched(BYW)

        current logic:
        get all SIDs from user watch history
        ->  remove SIDs whose cbf_list is similar to others

        output: one line for one byw_sid, user may have several lines for each SID he watched
        user_multi_account_id,byw_sid,sakuhin_codes,alt_score
        user_multi_account_id,byw_sid,sakuhin_codes,alt_score


        :param cbf_table_path: sakuhin_public_code, rs_list
        """
        # TODO: rerank by BPR, currrent workaround = no reranking <- may need A/B test

        logging.info("loading content-based filtering recommendation")
        cbf_dict = {}
        with open(cbf_table_path, 'r') as r:  # SID, SID|SID|...
            while True:
                line = r.readline()
                if line:
                    arrs = line.rstrip().split(",")
                    cbf_dict.setdefault(arrs[0], arrs[1])
                else:
                    break

        logging.info("loading postplay to complement cbf")
        with open(postplay_path, 'r') as r:  # SID, SID|SID|...
            while True:
                line = r.readline()
                if line:
                    arrs = line.rstrip().split(",")
                    cbf_recos = cbf_dict.get(arrs[0], None)
                    if cbf_recos:
                        cbf_recos = cbf_recos.split("|")
                        postplay_recos = [sid for sid in arrs[1].split("|") if sid not in cbf_recos]
                        cbf_dict[arrs[0]] = '|'.join(cbf_recos+postplay_recos)
                    else:
                        cbf_dict.setdefault(arrs[0], arrs[1])
                else:
                    break
        logging.info(f"cbf table has {len(cbf_dict)} items")


        logging.info("loading watched_list_ippan as user seen items")
        # TODO maintain a seen list for speed up
        dict_watched_sakuhin = {}  # {userid: [watched SIDs]}
        with open(watched_list_ippan, "r") as r:  # userid,item,rating ; rating != 1 -> bookmark
            while True:
                line = r.readline()
                if line:
                    arr = line.rstrip().split(",")
                    if arr[2] == '1':
                        userid = arr[0]
                        dict_watched_sakuhin[userid] = dict_watched_sakuhin.setdefault(userid, []) + [arr[1]]
                else:
                    break

        logging.info("making because_you_watched rows for new session users")
        with open(f"{self.alt_info['feature_public_code'].values[0]}.csv", "w") as w:
            w.write(self.config['header']['autoalt'])

            # read userid & sids
            for line_counter, (userid, session_sids) in enumerate(self.new_user_session_reader(input_path=user_sessions_path)):
                if line_counter%10000 == 1:
                    logging.info(f"{line_counter} lines done")

                # to record which session_sids are alive after removing similar SIDs.  SIDs:session_id
                session_dict = {cbf_dict[session_sid]:session_sid for session_sid in session_sids if cbf_dict.get(session_sid, None)}
                cbf_rs_lists = [k.split("|") for k, v in session_dict.items()]

                # check the similarity between cbf_rs_lists of SIDs
                similar_threshold = 0.5
                to_del = []
                while True:
                    if len(cbf_rs_lists) <= 1:
                        break

                    for i in range(len(cbf_rs_lists)-1):
                        for j in range(i+1, len(cbf_rs_lists)):
                            sa = set(cbf_rs_lists[i])
                            sb = set(cbf_rs_lists[j])
                            if max(len(sa & sb)/len(sa), len(sa & sb)/len(sb)) > similar_threshold:
                                to_del.append(cbf_rs_lists[j])
                        if to_del:
                            break
                    else:
                        break

                    if to_del:
                        for e in to_del:
                            cbf_rs_lists.remove(e)
                            del session_dict["|".join(e)]
                        to_del = []

                for SIDs, session_SID in session_dict.items():
                    watched_SIDs = set(dict_watched_sakuhin.get(userid, []))
                    # blacklist filtering & watched SID filtering
                    arrs = [sid for sid in SIDs.split("|") if sid not in self.blacklist and
                            sid not in watched_SIDs]

                    arrs = self.rm_series(arrs)

                    # TODO: current order of SIDs is based on cbf scores, we can mix cbf score with user bpr score
                    if len(arrs) >= self.min_nb_reco:
                        title = self.sid_name_dict.get(session_SID, None)
                        if title:
                            title = title.rstrip().replace('"','').replace("'","")
                            title = self.alt_info['feature_title'].values[0].replace("○○", title)

                            w.write(f"{userid},{self.alt_info['feature_public_code'].values[0]},{self.create_date},{'|'.join(arrs)},"
                                    f"{title},{self.alt_info['domain'].values[0]},1\n")

                            # TODO: for MVP, we only make one BYW FET
                            break
                        else:
                            logging.warning(f"{session_SID} can not find a mapping title")
                else:
                    pass

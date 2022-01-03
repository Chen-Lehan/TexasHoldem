import socket
import argparse

from utils.evaluator import HandEvaluator
from utils.card import Card
from utils.card import _fill_community_card
from utils.card import _pick_unused_card
from utils.client import recvJson, sendJson

class MonteCarloAgent:
    def __init__(self, room_id, name, game_number, bot, print_state):
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_ip = "holdem.ia.ac.cn"
        self.server_port = 18888
        self.room_number = 2           
        self.room_id = room_id
        self.name = name
        self.game_number = game_number
        self.bots = [bot]
        self.print_state = print_state


    def connect(self):
        self.client.connect((self.server_ip, self.server_port))
        message = dict(
            info = 'connect',
            room_id = self.room_id, 
            name = self.name, 
            room_number = self.room_number, 
            bots = self.bots,
            game_number = self.game_number
        )
        sendJson(self.client, message)
        self.game_number_left = self.game_number
        self.money_left = 20000
        self.oppo_money_left = 20000
        self.my_has_raise = 0
        self.oppo_has_raise = 0
        self.my_has_call = 0
        self.oppo_has_call = 0
        self.private_cards = []
        self.public_cards = []
        self.used_cards = []
        self.money_available_for_this_round = self.money_left / (self.game_number_left * 2)


    def ready(self):
        sendJson(self.client, {'info': 'ready', 'status': 'start'})
        self.game_number_left -= 1
        self.my_has_raise = 0
        self.oppo_has_raise = 0
        self.my_has_call = 0
        self.oppo_has_call = 0
        self.private_cards = []
        self.public_cards = []
        self.used_cards = []


    def send_action(self, action):
        sendJson(self.client, {'action': action, 'info': 'action'})


    def print_data(self, data):
        if data['info'] == 'state' and self.print_state == True:
            print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")
            print("info: ", data['info'])
            print("position: ", data['position'])
            print("action_position: ", data['action_position'])
            print("private_card: ", data['private_card'])
            print("players_num: ", len(data['players']))
            print("public_card: ", data['public_card'])
            print("legal_actions: ", data['legal_actions'])

            for player in data['players']:
                print("")
                print("player", data['players'].index(player), ": ")
                print("\tname: ", player['name'])
                print("\tposition: ", player['position'])
                print("\tmoney_left: ", player['money_left'])

            print("")
            print("history: ")
            for history in data['action_history']:
                print("\tround", data['action_history'].index(history), ": ")
                for history_in_a_round in history:
                        print("\t\t", history_in_a_round)
            print("++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++")


    def print_result(self, data):
        if data['info'] == 'result':
            print("**********************************************************************")
            print("info: ", data['info'])
            print("win money: ", data['players'][self.position]['win_money'])
            print("your card: ", data['player_card'][self.position])
            print("oppo card: ", data['player_card'][1 - self.position])
            print("public card: ", data['public_card'])
            print("**********************************************************************")
            

    def get_data(self, data):
        if data['info'] == 'state':
            self.position = data['position']
            getcard = lambda list : [Card.from_str(str) for str in list]
            self.private_cards = getcard(data['private_card'])
            self.public_cards = getcard(data['public_card'])
            self.used_cards = self.private_cards + self.public_cards
            self.legal_actions = data['legal_actions']

            player = data['players'][self.position]
            self.my_has_call = self.money_left - player['money_left']
            oppo_player = data['players'][1 - self.position]
            self.oppo_has_call = self.oppo_money_left - oppo_player['money_left']

            if data['action_history'][-1] != []:
                if data['action_history'][-1][-1]['position'] == 1 - self.position:
                    if data['action_history'][-1][-1]['action'][0] == 'r':
                        self.oppo_has_raise += int(data['action_history'][-1][-1]['action'][0][1:])


        elif data['info'] == 'result':
            self.money_left += data['players'][self.position]['win_money']
            self.oppo_money_left += data['players'][1 - self.position]['win_money']


    def get_action(self, simulation_times=1000):
        win_rate = self._estimate_hole_card_win_rate(simulation_times)
        print("win_rate: ", win_rate)
        if win_rate < .3:
            if "check" in self.legal_actions:
                return "check"
            else: 
                return "fold"

        elif win_rate < .6:
            if "check" in self.legal_actions:
                return "check"
            else: 
                call_prob = win_rate * self.my_has_call
                fold_prob = (1 - win_rate) * self.oppo_has_raise
                if call_prob < fold_prob:
                    return "fold"
                else:
                    return "call"

        elif win_rate < .7:
            if "check" in self.legal_actions:
                raise_prob = win_rate * (self.money_available_for_this_round - self.my_has_call)
                check_prob = (1 - win_rate) * self.my_has_call
                if raise_prob < check_prob or "raise" not in self.legal_actions:
                    return "check"
                else:
                    raise_value = int((self.money_available_for_this_round - self.my_has_call) * win_rate / 5)
                    self.my_has_raise += raise_value
                    return "r" + str(raise_value)
            else: 
                call_prob = win_rate * self.my_has_call
                fold_prob = (1 - win_rate) * self.oppo_has_raise
                if call_prob < fold_prob:
                    return "fold"
                else:
                    return "call"

        else:
            if self.my_has_call < self.money_available_for_this_round and "raise" in self.legal_actions:
                raise_value = int((self.money_available_for_this_round - self.my_has_call) * win_rate / 3)
                self.my_has_raise += raise_value
                return "r" + str(raise_value)
            else:
                if "call" in self.legal_actions:
                    return "call"
                else:
                    return "fold"


    def _montecarlo_simulation(self):
        community_cards = _fill_community_card(self.public_cards, self.used_cards)
        oppo_private_cards = _pick_unused_card(2, self.used_cards)
        my_score = HandEvaluator.eval_hand(self.private_cards, community_cards)
        oppo_score = HandEvaluator.eval_hand(oppo_private_cards, community_cards)
        return (my_score >= oppo_score)


    def _estimate_hole_card_win_rate(self, simulation_time):
        win_count = 0
        for _ in range(simulation_time):
            win_count += self._montecarlo_simulation() 
        
        return 1.0 * win_count / simulation_time



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--name', default="ahan")
    parser.add_argument('-r', '--room_id', type=int, default=1)
    parser.add_argument('-g', '--game_number', type=int, default=1)
    parser.add_argument('-b', '--bot', default="CallAgent")
    parser.add_argument('-s', '--not_print_state', action="store_true")
    
    args = parser.parse_args()
    print(args)

    room_id = args.room_id          # 进行对战的房间号
    name = args.name                # 当前程序的 AI 名字
    game_number = args.game_number  # 最大对局数量
    bots = [args.bot]               # 需要系统额外添加的智能体名字
    print_state = not args.not_print_state

    Agent = MonteCarloAgent(room_id, name, game_number, bots[0], print_state)
    Agent.connect()

    while True:
        data = recvJson(Agent.client)
        Agent.get_data(data)
        if data['info'] == 'state':
            if data['position'] == data['action_position']:
                Agent.print_data(data)
                action = Agent.get_action(10000)
                Agent.send_action(action)
        elif data['info'] == 'result':
            Agent.print_result(data)
            Agent.ready();
        else:
            print(data)
            break

    Agent.client.close()


if __name__ == "__main__":
    main()
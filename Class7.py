# info = {"add": "Taichung" ,"phone" : "0912345678" , "name" : "Steve" }
#
# for key in info:
#     print(key)
#     print(info[key])
from distutils.core import run_setup
from functools import total_ordering
from idlelib.debugger_r import restart_subprocess_debugger
from wsgiref.util import request_uri


# movie= [
#         {"title" : "Avengers:Endgame" ,"year" : "2019" , "box office(global)" : "2.799 B"},
# {"title" : "Avatar: The Way of Water" ,"year" : "2022" , "box office(global)" : "2.320 B"},
# {"title" : "Star Wars: The Force Awakens" ,"year" : "2015" , "box office(global)" : "2.071 B"},
# {"title" : "Avengers: Infinity War" ,"year" : "2018" , "box office(global)" : "2.052 B"}
#     ]
# for key in movie :
#     print("標題 : " , key["title"])
#     print("年分 : ", key["year"])
#     print("全球票房 : ", key["box office(global)"])
#     print("----------------")

# def fun01(tall):
#     print("我身高",tall,"公分")
# fun01(180)
# fun01(178)
# fun01(165)


# def menu(meal):
#
#     if meal == "A":
#         print("您點的是A套餐(漢堡+奶茶) = 100元")
#     elif meal == "B":
#         print("您點的是B套餐(薯條+紅茶) = 130元")
#     elif meal == "C":
#         print("您點的是C套餐(漢堡+薯條+可樂) = 150元")
#     else:
#         print("輸入錯誤，沒有此餐點")
#
# print("Hi , Lin，菜單如下")
# print("A套餐: 漢堡+奶茶 100元")
# print("B套餐: 薯條+紅茶 130元")
# print("C套餐: 漢堡+薯條+可樂 150元")
#
# x= input("請輸入您所需餐點(A\B\C) : ")
# menu
# def greet(name, gender):
#     if gender == "1":
#         print(name + "，先生您好")
#     elif gender == "2":
#         print(name + "，小姐您好")
#     else:
#         print("性別輸入錯誤，請輸入 1 或 2")
#
# # --- 主程式 ---
# user_name = input("請輸入姓名: ")
# user_gender = input("請輸入性別 (1=男 / 2=女): ")
#
# greet(user_name, user_gender)


# def plus(num1,num2,num3) :
#
#     total = num1+num2+num3
#     return total
# num1 = eval(input("請輸入數字1 :"))
# num2 = eval(input("請輸入數字2 :"))
# num3 = eval(input("請輸入數字3 :"))
# result = plus(num1, num2,num3)
# print(result)

# def shopping(num,price):
#     total = num * price
#     print("數量為" , num)
#     print("價格為", price)
#     print("總數為", total)
#     return total
#
# a = int(input("請輸入需要購買的數量 : "))
# b = int(input("請輸入單價 :"))
#
# result = shopping(a,b)
# print("您好，您購買的數量為 :", a ,"單價為", b,"元，總額是", result,"元")

def plus(num1 ,num2):
    x = num1+num2
    return x
def mul(num1,num2):
    x = num1-num2
    return x
def times(num1,num2):
    x = num1*num2
    return x
def div(num1,num2):
    if num2 == 0:
        return "error!! 除數不能為0"
    x = num1/num2
    return x
a = eval(input("請輸入第一個數字"))
b = eval(input("請輸入第二個數字"))
calc = input("請輸入 +、-、*、/ :\n")

if calc == "+":
    result =plus(a,b)
elif calc =="-":
    result = mul(a,b)
elif calc =="*":
    result = times(a,b)
elif calc == "/":
    result = div(a,b)
else:
    result = "無效運算，請重新輸入"
print("結果為",result)



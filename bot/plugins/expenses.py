from typing import Dict
from .plugin import Plugin
import requests
import json
from datetime import datetime

BASE_URL = 'https://expenses.darkube.app'

class expenses(Plugin):
    """
    A plugin to add, modify or view expense data.
    """

    def get_source_name(self) -> str:
        return "expenses"    
    
    
    
    def get_spec(self) -> [Dict]:
        return [
    {
        "name": "add_expense",
        "description": "Adds a new expense for a user.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "The category of the expense. select only one item from this list: Groceries, Recreation, Dining out, Transportation, Utilities, Rent, Insurance, Entertainment, Shopping, Health & Fitness, Travel, Education, Gifts & Donations, Personal Care, Home Maintenance, Debt Repayment "
                },
                "amount": {
                    "type": "number",
                    "description": "The amount of the expense."
                },
                "description": {
                    "type": "string",
                    "description": "description of the expense. guess from user inputs if its not provided specifically by the user"
                },
                "date": {
                    "type": "string",
                    "description": "date of the expense. If not provided, use today. accepted date format is YYYY_MM-DD."
                }
            },
            "required": ["category", "amount", "description", "date"]
        }
    },
    {
        "name": "get_expenses",
        "description": "Retrieves all expenses for a user.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "calculate_expenses",
        "description": "Calculates expenses for a user within a specified time frame and/or category. returns all expenses groupped by category if no time fram oor category is specified",
        "parameters": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "Optional start date for filtering expenses."
                },
                "end_date": {
                    "type": "string",
                    "description": "Optional end date for filtering expenses. accepted date format is YYYY_MM-DD."
                },
                "category": {
                    "type": "string",
                    "description": "Optional category for filtering expenses. accepted date format is YYYY_MM-DD."
                }
            },
            "required": []
        }
    },
    {
        "name": "get_highest_expense",
        "description": "Retrieves the category with the highest total expense for a user.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "modify_expense",
        "description": "Modifies an existing expense.",
        "parameters": {
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "the search term that is used to search 'expenses descriptions' to find the exact expense to modify"
                },
                "amount": {
                    "type": "number",
                    "description": "Optional new amount for the expense."
                },
                "category": {
                    "type": "string",
                    "description": "Optional new category for the expense. select only one item from this list: Groceries, Recreation, Dining out, Transportation, Utilities, Rent, Insurance, Entertainment, Shopping, Health & Fitness, Travel, Education, Gifts & Donations, Personal Care, Home Maintenance, Debt Repayment "
                },
                "description": {
                    "type": "string",
                    "description": "Optional new description for the expense."
                },
                "date": {
                    "type": "string",
                    "description": "Optional new date for the expense. accepted date format is YYYY_MM-DD."
                }
            },
            "required": ["search_term"]
        }
    }
]
        
      
        
    async def execute(self,function_name, helper, **kwargs) -> Dict:
        if function_name == 'add_expense':
            return self.add_expense(**kwargs)
        elif function_name == 'get_expenses':
            return self.get_expenses(**kwargs)
        elif function_name == 'calculate_expenses':
            return self.calculate_expenses(**kwargs)
        elif function_name == 'get_highest_expense':
            return self.get_highest_expense(**kwargs)
        elif function_name == 'modify_expense':
            return self.modify_expense(**kwargs)




    def add_expense(self, user_id, category, amount, description='', date=None):
        data = {"user_id": user_id, "category": category, "amount": amount, "description": description, "date": date}
        url = f'{BASE_URL}/add_expense'
        response = requests.post(url=url, json=data)
        return response.json()
    def modify_expense(self, user_id, amount=None, category=None, description=None, date=None, **kwargs):
        search_term = kwargs["term"]
        payload = {"amount": amount, "category": category, "description": description, "date": date}
        search_result = self.search_description(search_term, user_id)
        expense_id = search_result["closest_match_id"]
        url = f'{BASE_URL}/modify_expense/{expense_id}'
        response = requests.put(url=url, json=payload)
        return response.json()
    def calculate_expenses(self, user_id, start_date=None, end_date=None, category=None):
        params = {"user_id": user_id, "start_date": start_date, "end_date": end_date, "category": category}
        url = f'{BASE_URL}/calculate_expenses'
        response = requests.get(url=url, params=params)
        return response.json()
    def get_highest_expense(self, user_id):
        url = f'{BASE_URL}/get_highest_expense/{user_id}'
        response = requests.get(url=url)
    def get_expenses(self, user_id):
        url = f'{BASE_URL}/get_expenses/{user_id}'
        response = requests.get(url=url)
        return response.json()
    def search_description(self, search_term, user_id):
        params = {"description": search_term, "user_id": user_id}
        url = f'{BASE_URL}/search_description'
        response = requests.get(url=url, params=params)
        return response.json()

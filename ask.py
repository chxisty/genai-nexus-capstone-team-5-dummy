
import os
import json

from dotenv import load_dotenv
from groq import Groq
from rich.console import Console
from rich.markdown import Markdown

from helpdesk.database import (
    search_stations,
    search_trains,
    get_train_route,
    get_train_details,
)


# ==========================================
# INITIALIZATION
# ==========================================

console = Console(
    highlight=False,
    soft_wrap=False,
    width=None
)

# Reload values from .env even if already set
load_dotenv(override=True)

api_key = os.getenv("GROQ_API_KEY")

model = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
)

if not api_key:
    raise ValueError(
        "GROQ_API_KEY is missing from your .env file."
    )

client = Groq(api_key=api_key)


# ==========================================
# SYSTEM PROMPT
# ==========================================

SYSTEM_PROMPT = """
You are RailAssist, an intelligent Indian Railways
helpdesk assistant.

Answer railway questions using the available database tools.

RULES:

1. Use search_stations to identify station codes.
2. Use search_trains to find trains between stations.
3. Use get_train_details for train information.
4. Use get_train_route for scheduled stops.
5. Never invent train numbers, times, distances,
   station names or other railway information.
6. If information is unavailable, say so.
7. Use clear, readable Markdown formatting.
8. Avoid unnecessary database calls.
9. For station names, resolve station codes before
   searching for trains.
10. Do not request train details or routes unless needed.

CONVERSATION MEMORY:

11. Remember the conversation within the current session.
12. Understand follow-up references such as:
    - this train
    - it
    - that station
    - its arrival time
    - the same train
13. Resolve references using previous messages.
14. Reuse previously established train numbers.
15. Do not ask for information already provided.
16. Use existing tool results whenever sufficient.
17. Call additional tools when new information is needed.

FORMATTING:

18. Use two-column Markdown tables for train details.
19. Use tables for full train routes.
20. Include station codes, arrival and departure times.
21. Clearly distinguish scheduled stops from
    intermediate stops.
22. Keep short answers concise.
23. Do not print unnecessary information.
24. Explain that timetable information is scheduled,
    not live data.
25. Never claim to have real-time information unless
    an available tool actually provides it.
45. When converting duration_min into hours and minutes,
    use integer division by 60 for hours and modulo 60
    for remaining minutes.

46. Never independently estimate journey duration
    from formatted text.

47. For 280 minutes, always display 4 hours 40 minutes.
ADDITIONAL RULES:

26. Treat database tool results as the authoritative source.

27. Never assume the meaning of a database field.
    For example, zone and station code are different fields.

28. Never confuse duration_min with distance_km.

29. Use the exact field names returned by database tools.

30. Do not recommend connecting trains unless the
    connecting services have been verified using tools.

31. If no direct train is found, clearly state that
    no matching direct train was found in the dataset.
    Do not claim that no such train exists in reality.

32. Do not invent alternative routes or train schedules.

33. Conversation memory applies only to the current
    running session. Do not claim to remember information
    after the application restarts.
"""


# ==========================================
# CONVERSATION HISTORY
# ==========================================

conversation_messages = [
    {
        "role": "system",
        "content": SYSTEM_PROMPT
    }
]


# ==========================================
# AVAILABLE DATABASE TOOLS
# ==========================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_stations",
            "description": (
                "Search railway stations by name or code."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string"
                    }
                },
                "required": ["keyword"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_trains",
            "description": (
                "Find direct trains between two stations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_code": {
                        "type": "string"
                    },
                    "to_code": {
                        "type": "string"
                    }
                },
                "required": ["from_code", "to_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_train_route",
            "description": (
                "Get scheduled stops of a train."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "train_number": {
                        "type": "string"
                    }
                },
                "required": ["train_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_train_details",
            "description": (
                "Get details of a train by number."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "train_number": {
                        "type": "string"
                    }
                },
                "required": ["train_number"]
            }
        }
    }
]


# ==========================================
# EXECUTE DATABASE TOOLS
# ==========================================

def execute_tool(function_name, arguments):

    if function_name == "search_stations":
        return search_stations(**arguments)

    if function_name == "search_trains":
        return search_trains(**arguments)

    if function_name == "get_train_route":
        return get_train_route(**arguments)

    if function_name == "get_train_details":
        return get_train_details(**arguments)

    return {
        "error": f"Unknown tool: {function_name}"
    }


# ==========================================
# AI ASSISTANT
# ==========================================

def ask_question(question):

    # Work on a copy so failed API requests
    # do not corrupt conversation history.
    messages = list(conversation_messages)

    messages.append({
        "role": "user",
        "content": question
    })

    for _ in range(8):

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.2
        )

        assistant_message = response.choices[0].message

        messages.append(
            assistant_message.model_dump(
                exclude_none=True
            )
        )

        # No more tools required
        if not assistant_message.tool_calls:

            answer = (
                assistant_message.content
                or "No response generated."
            )

            # Save successful conversation
            conversation_messages[:] = messages

            return answer

        # Execute requested database tools
        for tool_call in assistant_message.tool_calls:

            function_name = tool_call.function.name

            try:
                arguments = json.loads(
                    tool_call.function.arguments
                )

                result = execute_tool(
                    function_name,
                    arguments
                )

            except Exception as error:
                result = {
                    "error": str(error)
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(
                    result,
                    default=str
                )
            })

    return (
        "I could not complete the request "
        "within the tool-call limit."
    )


# ==========================================
# TERMINAL INTERFACE
# ==========================================


def main():

    console.print()

    console.rule(
        "[bold cyan]RAILASSIST - AI RAILWAY HELPDESK[/bold cyan]"
    )

    console.print(
        "\nAsk me anything about Indian Railways!"
    )

    console.print(
        "[dim]Type 'reset' to clear conversation memory "
        "or 'exit' to stop.[/dim]\n"
    )

    while True:

        try:
            question = console.input(
                "[bold green]You:[/bold green] "
            ).strip()

            # Exit command
            if question.lower() in ["exit", "quit"]:

                console.print(
                    "\n[bold cyan]RailAssist:[/bold cyan] Goodbye!"
                )
                break

            # Reset conversation memory
            if question.lower() == "reset":

                conversation_messages[:] = [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    }
                ]

                console.print(
                    "\n[bold yellow]Conversation memory cleared![/bold yellow]\n"
                )

                continue

            if not question:
                continue

            # Single loading indicator
            with console.status(
                "[bold cyan]Loading.....[/bold cyan]",
                spinner="dots"
            ):
                answer = ask_question(question)

            # Display formatted answer
            console.print()
            console.print(
                "[bold cyan]RailAssist[/bold cyan]"
            )
            console.print(Markdown(answer))
            console.print()

        except KeyboardInterrupt:
            console.print(
                "\n[bold cyan]RailAssist:[/bold cyan] Goodbye!"
            )
            break

        except Exception as error:
            console.print(
                f"\n[bold red]Error:[/bold red] "
                f"{error}\n"
            )



# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":
    main()

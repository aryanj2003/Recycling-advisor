import os
import threading
import time

import geocoder
import psycopg2
import psycopg2.extras
import pygame
import requests
import sounddevice as sd
import speech_recognition as sr
from flask import Flask, jsonify, redirect, render_template, request, url_for
from flask_cors import CORS
from gtts import gTTS
from psycopg2 import Error

# Initialize Pygame
pygame.init()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

cached_location = None
recyclable_objects_cache = None
nonrecyclable_objects_cache = None
location_split = None

@app.route('/RecyclingAdvisorinfo.html')
def about_recycling_advisor():
    return render_template('RecyclingAdvisorinfo.html')

@app.route('/Me.html')
def about_developer():
    return render_template('Me.html')

@app.route('/Contact.html')
def contact_us():
    return render_template('Contact.html')

# Route for the UI
@app.route('/')
def home():
    return render_template('index.html')

#Define a new route to exit the program when you don't want to end it immediately
@app.route('/exit')
def exit_program():
    handle_exit()
    
# Define a new route to force exit the program
@app.route('/force_exit')
def force_exit():
    exit()

@app.route('/update_location', methods=['POST'])
def update_location():
    global cached_location, recyclable_objects_cache, nonrecyclable_objects_cache
    
    city = request.form.get('city')
    state = request.form.get('state')
    country = request.form.get('country')
    
    # Update the cached location
    cached_location = f"{city}, {state}, {country}"
    
    # Clear the cached recyclable and non-recyclable objects
    recyclable_objects_cache = None
    nonrecyclable_objects_cache = None
    
    # Redirect back to the home page
    return redirect(url_for('home'))

def get_location():
    '''
    Purpose: Retrieve the location information.
    Parameters: None
    Return value: Location as a string in the format "City, State, Country    
    '''
    global cached_location
    if cached_location:
        return cached_location
    g = geocoder.ip('me')
    if g.ok:
        location = f"{g.city}, {g.state}, {g.country}"
        cached_location = location
        return location
    else:
        return None

def fetch_recyclable_nonrecyclable_objects(location_split):
    '''
    Purpose: To get all the recycling and non recycling objects based on the user's location in the form of a list. We will get this data from a PostgresSQL database.
    Parameters: 
    recyclable_objects: A list containing all the recyclable objects for the user's location.
    nonrecyclable_objects: A list containing all the non-recyclable objects for the user's location.
    Return value: Two lists with one containing all of the recycling objects and the second list containing all of the non-recycling objects for the user's location.
    '''
    recyclable_objects = []
    nonrecyclable_objects = []
    global recyclable_objects_cache, nonrecyclable_objects_cache

    #Check if the data is already cached
    if recyclable_objects_cache and nonrecyclable_objects_cache:
        return recyclable_objects_cache, nonrecyclable_objects_cache
    conn = None  # Initialize conn outside the try block
    try:
        # Connects to an existing database
        conn = psycopg2.connect(host="ecs-pg.postgres.database.azure.com",port="5432",database="recycle",user="ecsadm@ecs-pg",password="Ecs$43210987",sslmode="require")
        print("Connected to the database.")
        # Creates a cursor to perform database operations
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        #Create a temporary table 
        postgreSQL_select_Query = """
        SELECT "Recyclable", "Non-recyclable"
        FROM public."Newrecycling_database"
        WHERE "City" = %s AND "State" = %s AND "Country" = %s
        """
        cursor.execute(postgreSQL_select_Query, (location_split[0], location_split[1], location_split[2]))
        recycle_by_city = cursor.fetchall()

        #Get the recyclable and non-recyclable items from each row
        for row in recycle_by_city:
            if row['Recyclable'] != None:
                recyclable_objects.append(row['Recyclable'])
                recyclable_objects = [item for item in recyclable_objects if item is not None]
            if row['Non-recyclable'] != None:
                nonrecyclable_objects.append(row['Non-recyclable'])
                nonrecyclable_objects = [item for item in nonrecyclable_objects if item is not None]

        #Cache the data locally
        recyclable_objects_cache = recyclable_objects
        nonrecyclable_objects_cache = nonrecyclable_objects

        print("Recyclable objects:", recyclable_objects)
        print("Non-recyclable objects:", nonrecyclable_objects)
    
        # Executing an SQL query
        cursor.execute("SELECT version();")
        # Fetches result
        record = cursor.fetchmany(12)
    except (Exception, psycopg2.Error) as error:
        print("Error while connecting to PostgreSQL:", error)
    finally:
        if conn:
            cursor.close()
            conn.close()

    # Returns PostgreSQL details
    return recyclable_objects_cache, nonrecyclable_objects_cache

def play_audio(text):
    '''
    Purpose: Convert the given text to audio and play it.
    Parameters:
    text: The text to be converted to audio and played.
    Return value: None
    '''
    global is_playing_audio
    is_playing_audio = True

    tts = gTTS(text=text, lang='en')
    tts.save('output.mp3')

    pygame.mixer.init()
    pygame.mixer.music.load('output.mp3')
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        if not is_playing_audio:
            pygame.mixer.music.stop()
            break
        time.sleep(1)

def play_audio_threaded(text):
    audio_thread = threading.Thread(target=play_audio, args=(text,))
    audio_thread.start()

def findifrecyclable(recycling_object_name, recyclable_objects, nonrecyclable_objects):
    '''
    Purpose: To determine if the object spoken by the user is recyclable or not.
    Parameters: recycling_object_name: The name of the recycling object
                recyclable_objects: The list of all the recycling objects.
                nonrecyclable objects: The list of all the non-recycling objects.
    Return value: Voice output for whether a given object is recyclable or not
    '''
    # Split the recycling_object_name into individual words
    input_words = recycling_object_name.lower()

    for recyclable_item in recyclable_objects:
        if recyclable_item.lower() in input_words:
            return f"{recyclable_item} goes in the recycling bin."

    for nonrecyclable_item in nonrecyclable_objects:
        if nonrecyclable_item.lower() in input_words:
            return f"{nonrecyclable_item} does not go in the recycling bin."

    # If no match is found, return a message indicating it's not recognized
    return "Sorry, I couldn't recognize that item for recycling."

def handle_exit():
    global is_playing_audio

    # Add any necessary cleanup operations here
    # For example, stopping audio playback if it's currently playing
    is_playing_audio = False  # Set the flag to stop audio playback

    # You can add more cleanup tasks if needed

    # Setup keyword recognizer for wake-up phrase
    keyword_recognizer = sr.Recognizer()

    # Ask the user if they want to exit the program
    play_audio_threaded('Would you like to exit the program?')

    # Clarify what the user wants to do if they halted the program in the middle
    with sr.Microphone() as audio_source:
        keyword_recognizer.adjust_for_ambient_noise(audio_source, duration=1)
        response_audio = keyword_recognizer.listen(audio_source)
        user_answer = keyword_recognizer.recognize_google(response_audio).lower()
        # If the response is yes, exit the program. Otherwise, continue listening for input
        if user_answer == 'yes':
            response = play_audio_threaded("Exiting the program")
            # You might want to add any necessary exit logic here
            return response  # This will terminate the program
        else:
            pass

def exit():
    response = play_audio_threaded("Exiting the program")
    return response 

# Route to execute the backend functionality
@app.route('/execute_backend', methods=['POST'])
def execute_backend():
    print("Executing the backend route.")
    global location_split
    edited_location = request.form.get('edited_location')  # Get the edited location from the form submission
    if edited_location:
        # greeting_played = False
        Initialtriggering_phase = False
        location = edited_location
        location_split = edited_location.split(', ')
        print("Location:", location)
        #Get the recyclable and non-recyclable objects based on the user's detected location
        recyclable_objects, nonrecyclable_objects = fetch_recyclable_nonrecyclable_objects(location_split)

        # Setup keyword recognizer for wake-up phrase
        keyword_recognizer = sr.Recognizer()

        try:
            # while not greeting_played:
            #     try:
            #         if not greeting_played:
            #             #Play the opening sound only once
            #             play_audio("Hello! Good day! Your recycling advisor is ready and rebooted for the day!")
            #             greeting_played = True
            #     except sr.UnknownValueError:
            #         #No wake-up phrase detected, continue listening
            #         pass
            #     except sr.RequestError as e:
            #         print("Could not request results from Google Web Speech API; {0}".format(e))

            while not Initialtriggering_phase:
                    if not Initialtriggering_phase:
                        #Play the initial triggering phase only once
                        play_audio("Speak now.")
                        Initialtriggering_phase = True

            while True:
                with sr.Microphone() as source:
                    keyword_recognizer.adjust_for_ambient_noise(source, duration=5) #Increase the duration
                    keyword_recognizer.energy_threshold = 300  # Adjust this value based on your microphone's sensitivity
                    audio = keyword_recognizer.listen(source)
                try:
                    #Check if the wake-up phrase is detected
                    wake_up_phrase = keyword_recognizer.recognize_google(audio).lower()
                    print("Wake-up phrase detected:", wake_up_phrase)

                    recyclable_found = any(recyclable_object.lower() in wake_up_phrase for recyclable_object in recyclable_objects)
                    nonrecyclable_found = any(nonrecyclable_object.lower() in wake_up_phrase for nonrecyclable_object in nonrecyclable_objects)
                    if recyclable_found or nonrecyclable_found:
                        result = findifrecyclable(wake_up_phrase, recyclable_objects, nonrecyclable_objects)
                        print("Result:", result)

                        #Output the result using the speaker
                        play_audio(result)

                        #Return the result
                        return f"<strong><span style='animation: blinker 1s linear infinite; font-size: 28px;'>{result}</span></strong>"
                    else:
                        #If the user does not give the correct Wake-up-phrase, continue listening until they do
                        play_audio("Please make sure that your Wake-up-phrase has the name of a recyclable or non-recyclable object.")
                        pass
                except EOFError:
                    # Redirect to the "/force_exit" route to gracefully exit the program
                    handle_exit()
                except sr.UnknownValueError:
                    play_audio("Sorry, I couldn't recognize the text you just spoke.")
                    pass
        except EOFError:
            force_exit()
    else:
        # greeting_played = False
        Initialtriggering_phase = False
        # Get the location
        location = get_location()
        location_split = location.split(', ')
        if location:
            print("Location:", location)
        else:
            print("Failed to retrieve location.")
        
        #Get the recyclable and non-recyclable objects based on the user's detected location
        recyclable_objects, nonrecyclable_objects = fetch_recyclable_nonrecyclable_objects(location_split)

        # Setup keyword recognizer for wake-up phrase
        keyword_recognizer = sr.Recognizer()

        try:
            # while not greeting_played:
            #     try:
            #         if not greeting_played:
            #             #Play the opening sound only once
            #             play_audio("Hello! Good day! Your recycling advisor is ready and rebooted for the day!")
            #             greeting_played = True
            #     except sr.UnknownValueError:
            #         #No wake-up phrase detected, continue listening
            #         pass
            #     except sr.RequestError as e:
            #         print("Could not request results from Google Web Speech API; {0}".format(e))

            while not Initialtriggering_phase:
                if not Initialtriggering_phase:
                    #Play the initial triggering phase only once
                    play_audio("Speak now")
                    Initialtriggering_phase = True

            while True:
                with sr.Microphone() as source:
                    keyword_recognizer.adjust_for_ambient_noise(source, duration=3) #Increase the duration
                    keyword_recognizer.energy_threshold = 300  # Adjust this value based on your microphone's sensitivity
                    audio = keyword_recognizer.listen(source)
                try:
                    #Check if the wake-up phrase is detected
                    wake_up_phrase = keyword_recognizer.recognize_google(audio).lower()
                    print("Wake-up phrase detected:", wake_up_phrase)

                    recyclable_found = any(recyclable_object.lower() in wake_up_phrase for recyclable_object in recyclable_objects)
                    nonrecyclable_found = any(nonrecyclable_object.lower() in wake_up_phrase for nonrecyclable_object in nonrecyclable_objects)
                    if recyclable_found or nonrecyclable_found:
                        result = findifrecyclable(wake_up_phrase, recyclable_objects, nonrecyclable_objects)
                        print("Result:", result)

                        #Output the result using the speaker
                        play_audio(result)

                        #Return the result
                        return f"<strong><span style='animation: blinker 1s linear infinite; font-size: 28px;'>{result}</span></strong>"
                    else:
                        #If the user does not give the correct Wake-up-phrase, continue listening until they do
                        play_audio("Please make sure that your Wake-up-phrase has the name of a recyclable or non-recyclable object.")
                        pass
                except EOFError:
                    # Redirect to the "/force_exit" route to gracefully exit the program
                    handle_exit()
                except sr.UnknownValueError:
                    play_audio("Sorry, I couldn't recognize the text you just spoke.")
                    pass
        except EOFError:
            force_exit()
     # Redirect back to the home page after backend execution and pass the detected location
    return render_template('index.html', detected_location=location, result=result)

if __name__ == '__main__':
    app.run(debug=True)
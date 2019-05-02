"""This module predict clickbait youtube videos."""
import argparse
import re
import warnings
import pickle
import emoji
import numpy as np
import pandas as pd
from gensim.parsing.preprocessing import *
from fastai.vision import *
import requests
from io import BytesIO

warnings.filterwarnings("ignore", category=DeprecationWarning)

def tokenize(string):
    """ Tokenizes a string.
    Adds a space between numbers and letters, removes punctuation, repeated whitespaces, words
    shorter than 2 characters, and stop-words. Returns a list of stems and, eventually, emojis.
    @param string: String to tokenize.
    @return: A list of stems and emojis.
    """

    # Based on the Ranks NL (Google) stopwords list, but "how" and "will" are not stripped, and
    # words shorter than 2 characters are not checked (since they are stripped):
    stop_words = [
        "about", "an", "are", "as", "at", "be", "by", "com", "for", "from", "in", "is", "it", "of",
        "on", "or", "that", "the", "this", "to", "was", "what", "when", "where", "who", "with",
        "the", "www"
    ]

    string = strip_short(
        strip_multiple_whitespaces(
            strip_punctuation(
                split_alphanum(string))),
        minsize=2)
    # Parse emojis:
    emojis = [c for c in string if c in emoji.UNICODE_EMOJI]
    # Remove every non-word character and stem each word:
    string = stem_text(re.sub(r"[^\w\s,]", "", string))
    # List of stems and emojis:
    tokens = string.split() + emojis

    for stop_word in stop_words:
        try:
            tokens.remove(stop_word)
        except:
            pass

    return tokens


def average_embedding(tokens, word2vec, na_vector=None):

    """ Embeds a title with the average representation of its tokens.
    Returns the mean vector representation of the tokens representations. When no token is in the
    Word2Vec model, it can be provided a vector to use instead (for example the mean vector
    representation of the train set titles).
    @param tokens: List of tokens to embed.
    @param word2vec: Word2Vec model.
    @param na_vector: Vector representation to use when no token is in the Word2Vec model.
    @return: A vector representation for the token list.
    """

    vectors = list()

    for token in tokens:
        if token in word2vec:
            vectors.append(word2vec[token])

    if len(vectors) == 0 and na_vector is not None:
        vectors.append(na_vector)

    return np.mean(np.array(vectors), axis=0)

def main():
    """
    This is the main function.
    """
    parser = argparse.ArgumentParser(description="Predict if a Youtube video is clickbait or not.")
    parser.add_argument(
        "--title", "-t",
        type=str, help="Title.", required=True)
    parser.add_argument(
        "--views", "-v",
        type=int, help="Number of views.", required=False)
    parser.add_argument(
        "--likes", "-l",
        type=int, help="Number of likes.", required=False)
    parser.add_argument(
        "--dislikes", "-d",
        type=int, help="Number of dislikes.", required=False)
    parser.add_argument(
        "--comments", "-c",
        type=int, help="Number of comments.", required=False)
    parser.add_argument(
        "--imageurl", "-i",
        type=str, help="Thumbnail image url.", required=False)
    args = parser.parse_args()


    # Import the Word2Vec model and the mean vector representation computed on the train set:
    word2vec = pickle.load(open("model/word2vec", "rb"))
    mean_title_embedding = pickle.load(open("model/mean-title-embedding", "rb"))


    input_data = {
        "video_title": args.title,
        "video_views": args.views if args.views is not None else np.NaN,
        "video_likes": args.likes if args.likes is not None else np.NaN,
        "video_dislikes": args.dislikes if args.dislikes is not None else np.NaN,
        "video_comments": args.comments if args.comments is not None else np.NaN,
    }
    sample = pd.DataFrame([input_data])

    # Tokenize the title and then compute its embedding:
    sample["video_title"] = sample["video_title"].apply(tokenize)
    sample["video_title"] = sample["video_title"].apply(
        average_embedding, word2vec=word2vec, na_vector=mean_title_embedding)
    sample = pd.concat(
        [
            sample[["video_views", "video_likes", "video_dislikes", "video_comments"]],
            sample["video_title"].apply(pd.Series)
        ], axis=1)
    # Compute the log of the video metadata or replace the missing values with the mean values
    # obtained from the train set:
    mean_log_video_views = pickle.load(open("model/mean-log-video-views", "rb"))
    mean_log_video_likes = pickle.load(open("model/mean-log-video-likes", "rb"))
    mean_log_video_dislikes = pickle.load(open("model/mean-log-video-dislikes", "rb"))
    mean_log_video_comments = pickle.load(open("model/mean-log-video-comments", "rb"))

    sample[["video_views", "video_likes", "video_dislikes", "video_comments"]] = \
        sample[["video_views", "video_likes", "video_dislikes", "video_comments"]].apply(np.log)

    if sample["video_views"].isnull().any():
        sample["video_views"].fillna(mean_log_video_views, inplace=True)
    if sample["video_likes"].isnull().any():
        sample["video_likes"].fillna(mean_log_video_likes, inplace=True)
    if sample["video_dislikes"].isnull().any():
        sample["video_dislikes"].fillna(mean_log_video_dislikes, inplace=True)
    if sample["video_comments"].isnull().any():
        sample["video_comments"].fillna(mean_log_video_comments, inplace=True)

    # Replace any -Inf value with 0:
    sample = sample.replace(-np.inf, 0)

    # Import the min-max scaler and apply it to the sample:
    min_max_scaler = pickle.load(open("model/min-max-scaler", "rb"))
    sample = pd.DataFrame(min_max_scaler.transform(sample), columns=sample.columns)

    # Import the SVM model:
    svm = pickle.load(open("model/svm", "rb"))
    # Print title prediction:
    title_pred = svm.predict_proba(sample)[0][1]


    # Load image model
    classes = ['clickbait','non_clickbait']
    path = os.getcwd()                
    data = ImageDataBunch.single_from_classes(path, classes, ds_tfms=get_transforms(), size=224).normalize(imagenet_stats)
    learn = cnn_learner(data, models.resnet34)
    learn.load('model/clickbait-model-2')
    img_data = BytesIO(requests.get(args.imageurl).content)
    im = open_image(img_data)
    # Print image prediction:
    img_pred = learn.predict(im)[2][0]
    # Print title prediction:
    title_pred = svm.predict_proba(sample)[0][1]

    # Print clickbait probability
    tensor = (img_pred+title_pred)/2
    tensor_list = list(str(tensor))
    result = float(''.join(tensor_list[7:-1]))
    return result
    return round(title_pred,4)

if __name__ == '__main__':
    print(main())

    #----------------------------------------------------------------------
# Matplotlib Rubik's cube simulator
# Author Jon Guan
# Forked from Jake Vanderplas https://github.com/jerpint/rubiks_cube_convnet
# Adapted from cube code written by David Hogg
#   https://github.com/davidwhogg/MagicCube

import numpy as np
import matplotlib.pyplot as plt
from matplotlib import widgets
from projection import Quaternion, project_points
import cube

"""
Sticker representation
----------------------
Each face is represented by a length [5, 3] array:

  [v1, v2, v3, v4, v1]

Each sticker is represented by a length [9, 3] array:

  [v1a, v1b, v2a, v2b, v3a, v3b, v4a, v4b, v1a]

In both cases, the first point is repeated to close the polygon.

Each face also has a centroid, with the face number appended
at the end in order to sort correctly using lexsort.
The centroid is equal to sum_i[vi].

Colors are accounted for using color indices and a look-up table.

With all faces in an NxNxN cube, then, we have three arrays:

  centroids.shape = (6 * N * N, 4)
  faces.shape = (6 * N * N, 5, 3)
  stickers.shape = (6 * N * N, 9, 3)
  colors.shape = (6 * N * N,)

The canonical order is found by doing

  ind = np.lexsort(centroids.T)

After any rotation, this can be used to quickly restore the cube to
canonical position.
"""

class InteractiveCube(plt.Axes):
    def __init__(self, cube=None,
                 interactive=True,
                 view=(0, 0, 10),
                 fig=None, rect=[0, 0.16, 1, 0.84],
                 **kwargs):
        if cube is None:
            self.cube = Cube(3)
        elif isinstance(cube, Cube):
            self.cube = cube
        else:
            self.cube = Cube(cube)

        self._view = view
        self._start_rot = Quaternion.from_v_theta((1, -1, 0),
                                                  -np.pi / 6)
        self._pycuber_rep = pc.Cube()

        if fig is None:
            fig = plt.gcf()

        # disable default key press events
        callbacks = fig.canvas.callbacks.callbacks
        del callbacks['key_press_event']

        # add some defaults, and draw axes
        kwargs.update(dict(aspect=kwargs.get('aspect', 'equal'),
                           xlim=kwargs.get('xlim', (-2.0, 2.0)),
                           ylim=kwargs.get('ylim', (-2.0, 2.0)),
                           frameon=kwargs.get('frameon', False),
                           xticks=kwargs.get('xticks', []),
                           yticks=kwargs.get('yticks', [])))
        super(InteractiveCube, self).__init__(fig, rect, **kwargs)
        self.xaxis.set_major_formatter(plt.NullFormatter())
        self.yaxis.set_major_formatter(plt.NullFormatter())

        self._start_xlim = kwargs['xlim']
        self._start_ylim = kwargs['ylim']

        # Define movement for up/down arrows or up/down mouse movement
        self._ax_UD = (1, 0, 0)
        self._step_UD = 0.01

        # Define movement for left/right arrows or left/right mouse movement
        self._ax_LR = (0, -1, 0)
        self._step_LR = 0.01

        self._ax_LR_alt = (0, 0, 1)

        # Internal state variable
        self._active = False  # true when mouse is over axes
        self._button1 = False  # true when button 1 is pressed
        self._button2 = False  # true when button 2 is pressed
        self._event_xy = None  # store xy position of mouse event
        self._shift = False  # shift key pressed
        self._digit_flags = np.zeros(10, dtype=bool)  # digits 0-9 pressed

        self._current_rot = self._start_rot  #current rotation state
        self._face_polys = None
        self._sticker_polys = None

        # Label Move list
        self._moveList = []

        self._draw_cube()

        # connect some GUI events
        self.figure.canvas.mpl_connect('button_press_event',
                                       self._mouse_press)
        self.figure.canvas.mpl_connect('button_release_event',
                                       self._mouse_release)
        self.figure.canvas.mpl_connect('motion_notify_event',
                                       self._mouse_motion)
        self.figure.canvas.mpl_connect('key_press_event',
                                       self._key_press)
        self.figure.canvas.mpl_connect('key_release_event',
                                       self._key_release)

        self._initialize_widgets()

        # write some instructions
        self.figure.text(0.05, 0.05,
                         "Mouse/arrow keys adjust view\n"
                         "U/D/L/R/B/F keys turn faces\n"
                         "(hold shift for counter-clockwise)",
                         size=10)

    def _initialize_widgets(self):
        self._ax_reset = self.figure.add_axes([0.75, 0.05, 0.2, 0.075])
        self._btn_reset = widgets.Button(self._ax_reset, 'Reset View')
        self._btn_reset.on_clicked(self._reset_view)

        self._ax_solve = self.figure.add_axes([0.55, 0.05, 0.2, 0.075])
        self._btn_solve = widgets.Button(self._ax_solve, 'Reset Cube')
        self._btn_solve.on_clicked(self._reset_cube)

        self._ax_shuffle = self.figure.add_axes([0.8, 0.9, 0.23, 0.075])
        self._btn_shuffle = widgets.Button(self._ax_shuffle, 'Shuffle')
        self._btn_shuffle.on_clicked(self._shuffle_cube)

        self._ax_solveNN = self.figure.add_axes([0.8, 0.75, 0.2, 0.075])
        self._btn_solveNN = widgets.Button(self._ax_solveNN, 'Solve')
        self._btn_solveNN.on_clicked(self._solve_cube_NN)

    def _project(self, pts):
        return project_points(pts, self._current_rot, self._view, [0, 1, 0])

    def _draw_cube(self):
        stickers = self._project(self.cube._stickers)[:, :, :2]
        faces = self._project(self.cube._faces)[:, :, :2]
        face_centroids = self._project(self.cube._face_centroids[:, :3])
        sticker_centroids = self._project(self.cube._sticker_centroids[:, :3])

        plastic_color = self.cube.plastic_color
        colors = np.asarray(self.cube.face_colors)[self.cube._colors]
        face_zorders = -face_centroids[:, 2]
        sticker_zorders = -sticker_centroids[:, 2]

        if self._face_polys is None:
            # initial call: create polygon objects and add to axes
            self._face_polys = []
            self._sticker_polys = []

            for i in range(len(colors)):
                fp = plt.Polygon(faces[i], facecolor=plastic_color,
                                 zorder=face_zorders[i])
                sp = plt.Polygon(stickers[i], facecolor=colors[i],
                                 zorder=sticker_zorders[i])

                self._face_polys.append(fp)
                self._sticker_polys.append(sp)
                self.add_patch(fp)
                self.add_patch(sp)
        else:
            # subsequent call: update the polygon objects
            for i in range(len(colors)):
                self._face_polys[i].set_xy(faces[i])
                self._face_polys[i].set_zorder(face_zorders[i])
                self._face_polys[i].set_facecolor(plastic_color)

                self._sticker_polys[i].set_xy(stickers[i])
                self._sticker_polys[i].set_zorder(sticker_zorders[i])
                self._sticker_polys[i].set_facecolor(colors[i])

        self.figure.canvas.draw()

    def rotate(self, rot):
        self._current_rot = self._current_rot * rot

    def rotate_face(self, face, turns=1, layer=0, steps=5):
        if not np.allclose(turns, 0):
            for i in range(steps):
                self.cube.rotate_face(face, turns * 1. / steps,
                                      layer=layer)
                self._draw_cube()

    def _reset_view(self, *args):
        self.set_xlim(self._start_xlim)
        self.set_ylim(self._start_ylim)
        self._current_rot = self._start_rot
        self._draw_cube()

    def _reset_cube(self, *args):
        move_list = self.cube._move_list[:]
        for (face, n, layer) in move_list[::-1]:
            self.rotate_face(face, -n, layer, steps=3)
        self.cube._move_list = []

        self._pycuber_rep = pc.Cube()

        self._resetLabels()

    def _resetLabels(self):
        try:
            self.scrambleLabel.remove()
            self.scrambleLabel = None
            self.solutionLabel.remove()
            self.solutionLabel = None
        except AttributeError:
            print('no scramblelabel')
        self.figure.canvas.draw()

    def _printShuffleLabel(self, moves):
        try:
            self.scrambleLabel.remove()
            self.scrambleLabel = None
        except AttributeError:
            print('no scrambleLabel')
        self.scrambleLabel = self.figure.text(0.05,0.95, str(moves), fontsize=10)
        self.figure.canvas.draw()


    def _shuffle_cube(self, *args):
        self._reset_cube(self, *args)
        cube_scrambled,scramble_instructions,solution = generate_game(max_moves = max_moves)
        self._moveList = scramble_instructions
        # plot scramble_instructions

        print(str(scramble_instructions))
        self._printShuffleLabel(scramble_instructions)




        for j in scramble_instructions:

            self._pycuber_rep(str(j))

            if(len(str(j))==1):
                self.rotate_face(str(j)[0])

            else:
                if(str(j)[1]=="'"):
                    self.rotate_face(str(j)[0],-1)
                    #c.rotate_face(j)
                elif(str(j)[1]=="2"):
                    self.rotate_face(str(j)[0])
                    self.rotate_face(str(j)[0])

        #self._pycuber_rep = cube_scrambled

    def _solve_cube_NN(self, *args):
        print('solving...')

        global model

        cube_solved = pc.Cube()
        cube = self._pycuber_rep
        moves = []
        for j in range(10):
            move = self._convertPycubeToMove(cube)
            moves.append(move)
            cube(move)
            if cube == cube_solved:
                break
        print(str(moves))

        try:
            self.solutionLabel.remove()
            self.solutionLabel = None
        except AttributeError:
            print('no solutionLabel')
        self.solutionLabel = self.figure.text(0.05,0.9, str(moves), fontsize=10)


        for j in moves:
            if(len(str(j))==1):
                self.rotate_face(str(j)[0])
            else:
                if(str(j)[1]=="'"):
                    self.rotate_face(str(j)[0],-1)
                    #c.rotate_face(j)
                elif(str(j)[1]=="2"):
                    self.rotate_face(str(j)[0])
                    self.rotate_face(str(j)[0])

    def _convertPycubeToMove(self, cube):
        cube_np = cube2np(cube)
        cube_np = np.reshape(cube_np,(1,18,3,1))
        move = possible_moves[np.argmax(model.predict(cube_np))]
        return move

    def _key_press(self, event):
        """Handler for key press events"""
        #matplotlib does not detect shift events by itself
        if event.key.isdigit():
            self._digit_flags[int(event.key)] = 1
        elif event.key == 'right' or event.key == 'shift+right':
            if event.key == 'shift+right':
                ax_LR = self._ax_LR_alt
            else:
                ax_LR = self._ax_LR
            self.rotate(Quaternion.from_v_theta(ax_LR,
                                                5 * self._step_LR))
        elif event.key == 'shift+left' or event.key == 'left':
            if event.key=='shift+left':
                ax_LR = self._ax_LR_alt
            else:
                ax_LR = self._ax_LR
            self.rotate(Quaternion.from_v_theta(ax_LR,
                                                -5 * self._step_LR))
        elif event.key == 'up':
            self.rotate(Quaternion.from_v_theta(self._ax_UD,
                                                5 * self._step_UD))
        elif event.key == 'down':
            self.rotate(Quaternion.from_v_theta(self._ax_UD,
                                                -5 * self._step_UD))
        elif event.key.upper() in 'LRUDBF':
            if event.key in 'LRUDBF':
                direction = -1
            else:
                direction = 1

            sanitizedMove = event.key.upper() + "" if direction == 1 else "'"
            if np.any(self._digit_flags[:self.cube.N]):
                for d in np.arange(self.cube.N)[self._digit_flags[:self.cube.N]]:
                    self.rotate_face(event.key.upper(), direction, layer=d)
                    self._pycuber_rep(sanitizedMove)
            else:
                self.rotate_face(event.key.upper(), direction)
                self._pycuber_rep(sanitizedMove)

            self._moveList.append(sanitizedMove)

            print(str(self._moveList))
            self._printShuffleLabel(self._moveList)
            self._draw_cube()


    def _key_release(self, event):
        """Handler for key release event"""
        if event.key == 'shift':
            self._shift = False
        elif event.key.isdigit():
            self._digit_flags[int(event.key)] = 0

    def _mouse_press(self, event):
        """Handler for mouse button press"""
        self._event_xy = (event.x, event.y)
        if event.button == 1:
            self._button1 = True
        elif event.button == 3:
            self._button2 = True

    def _mouse_release(self, event):
        """Handler for mouse button release"""
        self._event_xy = None
        if event.button == 1:
            self._button1 = False
        elif event.button == 3:
            self._button2 = False

    def _mouse_motion(self, event):
        """Handler for mouse motion"""
        if self._button1 or self._button2:
            dx = event.x - self._event_xy[0]
            dy = event.y - self._event_xy[1]
            self._event_xy = (event.x, event.y)

            if self._button1:
                if self._shift:
                    ax_LR = self._ax_LR_alt
                else:
                    ax_LR = self._ax_LR
                rot1 = Quaternion.from_v_theta(self._ax_UD,
                                               self._step_UD * dy)
                rot2 = Quaternion.from_v_theta(ax_LR,
                                               self._step_LR * dx)
                self.rotate(rot1 * rot2)

                self._draw_cube()

            if self._button2:
                factor = 1 - 0.003 * (dx + dy)
                xlim = self.get_xlim()
                ylim = self.get_ylim()
                self.set_xlim(factor * xlim[0], factor * xlim[1])
                self.set_ylim(factor * ylim[0], factor * ylim[1])

                self.figure.canvas.draw()


def generate_game(max_moves = 1):

    # generate a single game with max number of permutations number_moves

    mycube = pc.Cube()

    global possible_moves
    formula = []
    number_moves = max_moves#randint(3,max_moves)
    for j in range(number_moves):
        formula.append(possible_moves[randint(0,len(possible_moves)-1)])

    #my_formula = pc.Formula("R U R' U' D' R' F R2 U' D D R' U' R U R' D' F'")

    my_formula = pc.Formula(formula)


    mycube = mycube((my_formula))
    # use this instead if you want it in OG data type
    scramble_instructions = my_formula.copy()
    cube_scrambled = mycube.copy()

    solution = my_formula.reverse()

    #print(mycube)


    return cube_scrambled,formula,solution

def cube2np(mycube):
    # transform cube object to np array
    # works around the weird data type used
    global faces
    global colors
    cube_np = np.zeros((6,3,3))
    for i,face in enumerate(faces):
        face_tmp = mycube.get_face(face)
        for j in range(3):
            for k in range(len(face_tmp[j])):
                caca = face_tmp[j][k]
                cube_np[i,j,k] = colors.index(str(caca))
    return cube_np


if __name__ == '__main__':
    import keras
    from keras.models import load_model
    import pycuber as pc
    import sys
    import numpy as np

    from    random import randint
    possible_moves = ["R","R'","R2","U","U'","U2","F","F'","F2","D","D'","D2","B","B'","B2","L","L'","L2"]
    faces = ['L','U','R','D','F','B'] # for pycuber
    colors = ['[r]','[y]','[o]','[w]','[g]','[b]'] #for pycuber

    max_moves  = 6

    model = load_model('rubiks_model.h5')

    try:
        N = int(sys.argv[1])
    except:
        N = 3

    c = Cube(N)


    # # do a 3-corner swap
    # for j in scramble_instructions:
    #     if(len(str(j))==1):
    #         c.rotate_face(str(j)[0])
    #     else:
    #         if(str(j)[1]=="'"):
    #             c.rotate_face(str(j)[0],-1)
    #             #c.rotate_face(j)
    #         elif(str(j)[1]=="2"):
    #             c.rotate_face(str(j)[0])
    #             c.rotate_face(str(j)[0])
    #c.rotate_face('D')
    #c.rotate_face('R', -1)
    #c.rotate_face('U', -1)
    #c.rotate_face('R')
    #c.rotate_face('D', -1)
    #c.rotate_face('R', -1)
    #c.rotate_face('U')
    #c.rotate_face('U')
    c.draw_interactive()
    #c.rotate_face('U')

    plt.show()

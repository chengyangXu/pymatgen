#!/usr/bin/env python

"""
Module containing analysis classes which compute a pourbaix diagram given a target
compound/element.
"""

from __future__ import division

__author__ = "Sai Jayaraman"
__copyright__ = "Copyright 2012, The Materials Project"
__version__ = "0.0"
__maintainer__ = "Sai Jayaraman"
__email__ = "sjayaram@mit.edu"
__status__ = "Development"
__date__ = "Nov 1, 2012"

PREFAC = 0.0591
MU_H2O = -2.4583

import logging
import numpy as np
import itertools
import re
from pyhull.convex_hull import ConvexHull
from pymatgen.analysis.pourbaix.entry import MultiEntry
from pymatgen.core.periodic_table import Element
from pymatgen.core import Composition
from pymatgen.core.ion import Ion

logger = logging.getLogger(__name__)


class PourbaixDiagram(object):
    """
    Class to create a Pourbaix diagram from entries
    """
    def __init__(self, entries, comp_dict = {}):
        """
        Args:
            entries:
                Entries list containing both Solids and Ions
            comp_dict:
                Dictionary of compositions 
        """
        self._solid_entries = list()
        self._ion_entries = list()
        for entry in entries:
            if entry.phase_type == "Solid":
                self._solid_entries.append(entry)
            elif entry.phase_type == "Ion":
                self._ion_entries.append(entry)
            else:
                raise StandardError("Incorrect Phase type - needs to be \
                Pourbaix entry of phase type Ion/Solid")
        self._unprocessed_entries = self._solid_entries + self._ion_entries
        self._elt_comp = comp_dict
        if comp_dict:
            self._multielement = True
            self.pourbaix_elements = [key for key in comp_dict]
            w = [comp_dict[key] for key in comp_dict]
            A = []
            for comp in comp_dict:
                m = re.search(r"\[([^\[\]]+)\]|\(aq\)", comp)
                if m:
                    comp_obj = Ion.from_formula(comp)
                else:
                    comp_obj = Composition.from_formula(comp)
                Ai = []
                for elt in self.pourbaix_elements:
                    Ai.append(comp_obj[Element(elt)])
                A.append(Ai)
            A = ((np.array(A)).T).astype(float)
            w = np.array(w)
            A /= np.dot([A[i].sum() for i in xrange(len(A))], w)
            x = np.linalg.solve(A, w)
            self._elt_comp = dict(zip(self.pourbaix_elements, x))

        else:
            self._multielement = False
            self.pourbaix_elements = [el.symbol for el in entries[0].composition.elements if el.symbol not in ["H", "O"]]
        self._make_pourbaixdiagram()

    def _create_conv_hull_data(self):
        """
        Make data conducive to convex hull generator.
        """
        if self._multielement:
            self._all_entries = self._process_multielement_entries()
        else:
            self._all_entries = self._unprocessed_entries
        entries_to_process = list()
        for entry in self._all_entries:
            entry.scale(entry.normalization_factor)
            entry.correction += (- MU_H2O * entry.nH2O + entry.conc_term)
            entries_to_process.append(entry)
        self._qhull_entries = entries_to_process
        return self._process_conv_hull_data(entries_to_process)

    def _process_conv_hull_data(self, entries_to_process):
        """
        From a sequence of ion+solid entries, generate the necessary data
        for generation of the convex hull.
        """
        data = []
        for entry in entries_to_process:
            row = [entry.npH, entry.nPhi, entry.g0]
            data.append(row)
        temp = zip(data, self._qhull_entries)
        temp.sort(key=lambda x: x[0][2])
        [data, self._qhull_entries] = zip(*temp)
        return data

    def _process_multielement_entries(self):
        """
        Create entries for multi-element Pourbaix construction
        """
        N = len(self._elt_comp) # No. of elements
        entries = self._unprocessed_entries
        elt_list = self._elt_comp.keys()
        composition_list = [self._elt_comp[el] for el in elt_list]
        list_of_entries = list(itertools.combinations([i for i in xrange(len(entries))], N))
        processed_entries = list()
        self._entry_components_list = list_of_entries
        self._entry_components_dict = {}
        for entry_list in list_of_entries:
            A = [[0.0 for i in xrange(1, len(elt_list))] for j in xrange(1, len(entry_list))]
            multi_entries = [entries[j] for j in entry_list]
            sum_nel = 0.0
            entry0 = entries[entry_list[0]]
            if entry0.phase_type == "Solid":
                red_fac = entry0.composition.get_reduced_composition_and_factor()[1]
            else:
                red_fac = 1.0
            for i in xrange(len(elt_list)):
                sum_nel += entry0.composition[Element(elt_list[i])] / red_fac
            b = [entry0.composition[Element(elt_list[i])] / red_fac -
                 composition_list[i] * sum_nel for i in xrange(1, len(elt_list))]
            for j in xrange(1, len(entry_list)):
                entry = entries[entry_list[j]]
                if entry.phase_type == "Solid":
                    red_fac = entry.composition.get_reduced_composition_and_factor()[1]
                else:
                    red_fac = 1.0
                sum_nel = 0.0
                for el in self._elt_comp:
                    sum_nel += entry.composition[Element(el)] / red_fac
                for i in xrange(1, len(elt_list)):
                    el = elt_list[i]
                    A[i-1][j-1] = composition_list[i] * sum_nel - entry.composition[Element(el)] / red_fac
            try:
                weights = np.linalg.solve(np.array(A), np.array(b))
            except np.linalg.linalg.LinAlgError as err:
                if 'Singular matrix' in err.message:
                    continue
                else:
                    raise StandardError("Unknown Error message!")
            if not(np.all(weights > 0.0)):
                continue
            weights = list(weights)
            weights.insert(0, 1.0)
            super_entry = MultiEntry(multi_entries, weights)
            self._entry_components_dict[super_entry] = entry_list
            processed_entries.append(super_entry)
        self._entry_components_dict[super_entry] = entry_list
        processed_entries.append(super_entry)
        return processed_entries

    def _make_pourbaixdiagram(self):
        """
        Calculates entries on the convex hull in the dual space.
        """
        stable_entries = set()
        self._qhull_data = self._create_conv_hull_data()
        dim = len(self._qhull_data[0])
        if len(self._qhull_data) < dim:
            raise StandardError("Can only do elements with at-least 3 entries for now")
        if len(self._qhull_data) == dim:
            self._facets = [range(dim)]
            vertices = set(list(itertools.chain(*self._facets)))

        else:
            facets_pyhull = np.array(ConvexHull(self._qhull_data).vertices)
            self._facets = np.sort(np.array(facets_pyhull))
            logger.debug("Final facets are\n{}".format(self._facets))

            logger.debug("Removing vertical facets...")
            vert_facets_removed = list()
            for facet in self._facets:
                facetmatrix = np.zeros((len(facet), len(facet)))
                count = 0
                for vertex in facet:
                    facetmatrix[count] = np.array(self._qhull_data[vertex])
                    facetmatrix[count, dim - 1] = 1
                    count += 1
                if abs(np.linalg.det(facetmatrix)) > 1e-8:
                    vert_facets_removed.append(facet)
                else:
                    print "removed facet", facet
                    logger.debug("Removing vertical facet : {}".format(facet))

            logger.debug("Removing UCH facets by eliminating normal.z >0 ...")

            # Find center of hull
            vertices = set()
            for facet in vert_facets_removed:
                for vertex in facet:
                    vertices.add(vertex)
            c = [0.0, 0.0, 0.0]
            c[0] = np.average([self._qhull_data[vertex][0] for vertex in vertices])
            c[1] = np.average([self._qhull_data[vertex][1] for vertex in vertices])
            c[2] = np.average([self._qhull_data[vertex][2] for vertex in vertices])

            # Shift origin to c
            new_qhull_data = np.array(self._qhull_data)
            for vertex in vertices:
                new_qhull_data[vertex] -= c

            # For each facet, find normal n, find dot product with P, and check if this is -ve
            final_facets = list()
            for facet in vert_facets_removed:
                a = new_qhull_data[facet[1]] - new_qhull_data[facet[0]]
                b = new_qhull_data[facet[2]] - new_qhull_data[facet[0]]
                n = np.cross(a, b)
                val = np.dot(n, new_qhull_data[facet[0]])
                if val < 0:
                    n = -n
                if n[2] <= 0:
                    final_facets.append(facet)
                else:
                    print "removed UCH facet", facet
                    logger.debug("Removing UCH facet : {}".format(facet))
            final_facets = np.array(final_facets)
            self._facets = final_facets

        stable_vertices = set()
        for facet in self._facets:
            for vertex in facet:
                stable_vertices.add(vertex)
                stable_entries.add(self._qhull_entries[vertex])
        self._stable_entries = stable_entries
        self._vertices = stable_vertices

    @property
    def facets(self):
        """
        Facets of the convex hull in the form of  [[1,2,3],[4,5,6]...]
        """
        return self._facets

    @property
    def qhull_data(self):
        """
        Data used in the convex hull operation. This is essentially a matrix of
        composition data and energy per atom values created from qhull_entries.
        """
        return self._qhull_data

    @property
    def qhull_entries(self):
        """
        Return qhull entries
        """
        return self._qhull_entries

    @property
    def stable_entries(self):
        """
        Returns the stable entries in the phase diagram.
        """
        return self._stable_entries

    @property
    def all_entries(self):
        """
        Return all entries
        """
        return self._all_entries

    @property
    def vertices(self):
        """
        Return vertices of the convex hull
        """
        return self._vertices

    @property
    def unprocessed_entries(self):
        """
        Return unprocessed entries
        """
        return self._unprocessed_entries
